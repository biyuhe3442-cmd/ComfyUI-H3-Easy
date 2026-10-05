"""Temporal State Transport (TST) for MiniMax H3.

Adapted from the official TST implementation (lytang63/temporal-state-transport,
MIT, arXiv:2609.08505; see THIRD_PARTY_NOTICES.md) for H3's packed attention.

Per DiT block, the frame-to-frame attention of the video tokens is measured at a
subset of spatial positions. Its spectral entropy and off-diagonal mass give a
balance score q in [0, 0.25]; the block's attention output for the video rows is
multiplied by 1 + tau * layer_weight * step_weight * q. Layer weight grows with
depth and step weight fades over the denoising schedule, as in the reference.
H3's attention out-projection has no bias, so scaling before it equals the
reference's post-projection scaling.
"""

from __future__ import annotations

import math
from functools import partial

import torch

import comfy.patcher_extension

WRAPPER_KEY = "h3easy_tst"
MAX_POSITIONS = 96
EPS = 1e-8


class TSTState:
    def __init__(self, tau: float, total_layers: int):
        self.tau = float(tau)
        self.total_layers = max(1, int(total_layers))
        self.schedule: list[float] = []
        self.layer = 0
        self.step_weight = 1.0
        self.scales: list[float] = []

    def set_schedule(self, sigmas):
        self.schedule = [float(s) for s in sigmas]

    def begin_forward(self, sigma: float):
        self.layer = 0
        if len(self.schedule) > 1:
            steps = len(self.schedule) - 1
            index = min(range(steps), key=lambda i: abs(self.schedule[i] - sigma))
            self.step_weight = 0.5 + 0.5 * math.cos(math.pi * index / max(1, steps - 1))
        else:
            self.step_weight = 1.0

    def layer_weight(self) -> float:
        if self.total_layers == 1:
            return 1.0
        position = min(self.layer, self.total_layers - 1)
        return 0.5 - 0.5 * math.cos(math.pi * position / (self.total_layers - 1))


def balance_score(q_video: torch.Tensor, k_video: torch.Tensor, frames: int, rows: int) -> float:
    """TST balance score from video queries/keys shaped [1, heads, frames*rows, dim]."""
    heads, dim = q_video.shape[1], q_video.shape[-1]
    q = q_video[0].reshape(heads, frames, rows, dim)
    k = k_video[0].reshape(heads, frames, rows, dim)
    if rows > MAX_POSITIONS:
        index = torch.linspace(0, rows - 1, MAX_POSITIONS, device=q.device).round().long()
        q = q.index_select(2, index)
        k = k.index_select(2, index)
    q = q.permute(2, 0, 1, 3).float() * dim ** -0.5     # [P, heads, F, dim]
    k = k.permute(2, 0, 1, 3).float()
    attn = (q @ k.transpose(-2, -1)).softmax(dim=-1).reshape(-1, frames, frames)

    diag_mean = torch.diagonal(attn.mean(dim=0)).mean()
    temporal_alpha = (1.0 - diag_mean).clamp(0.0, 1.0)

    gram = attn @ attn.transpose(-2, -1)
    trace = torch.diagonal(gram, dim1=-2, dim2=-1).sum(dim=-1).clamp(min=EPS)
    rho = (gram / trace[:, None, None]).mean(dim=0)
    rho = rho / torch.diagonal(rho).sum().clamp(min=EPS)
    rho = (0.5 * (rho + rho.transpose(0, 1))).double().cpu()
    if not bool(torch.isfinite(rho).all()):
        return 0.0
    eig = _spectrum(rho)
    if eig is None:
        return 0.0
    eig = eig.clamp(min=EPS)
    eig = eig / eig.sum()
    entropy = float(-(eig * eig.log()).sum() / math.log(frames))
    entropy = min(1.0, max(0.0, entropy))
    return float(temporal_alpha) * entropy * (1.0 - entropy)


def _spectrum(rho: torch.Tensor):
    """Eigenvalues of a symmetric PSD matrix; None if LAPACK gives up.

    Nearly uniform attention makes rho close to rank one with many repeated zero
    eigenvalues, where eigh occasionally fails to converge; the SVD route is more
    forgiving and gives the same values for PSD input.
    """
    try:
        return torch.linalg.eigvalsh(rho)
    except RuntimeError:
        pass
    try:
        return torch.linalg.svdvals(rho)
    except RuntimeError:
        return None


def _video_span(layout):
    for start, stop, kind in reversed(layout.segments):
        if kind == "video":
            return start, stop
    return None


def _override(state: TSTState, previous, func, q, k, v, heads, *args, **kwargs):
    options = kwargs.get("transformer_options") or {}
    layout = options.get("minimax_h3_layout")
    span = None
    scale = 1.0
    if layout is not None and q.ndim == 4 and q.shape[-2] == layout.seq_len:
        span = _video_span(layout)
        _, latent_t, lat_h, lat_w, _ = layout.signature
        rows = (lat_h // 2) * (lat_w // 2)
        if span is not None and latent_t >= 2 and span[1] - span[0] == latent_t * rows:
            a, b = span
            score = balance_score(q[..., a:b, :], k[..., a:b, :], latent_t, rows)
            scale = 1.0 + state.tau * state.layer_weight() * state.step_weight * score
            state.scales.append(scale)
        state.layer += 1
    if previous is not None:
        out = previous(func, q, k, v, heads, *args, **kwargs)
    else:
        out = func(q, k, v, heads, *args, **kwargs)
    if span is not None and scale != 1.0:
        a, b = span
        out[..., a:b, :] *= scale
    return out


def _forward_wrapper(state: TSTState, executor, x, timestep, context, transformer_options, *args, **kwargs):
    state.begin_forward(float(timestep.flatten()[0]) / 1000.0)
    return executor(x, timestep, context, transformer_options, *args, **kwargs)


def apply_tst(model, tau: float, schedule) -> tuple[object, TSTState]:
    """Return a patched clone of ``model`` and its state (for reporting)."""
    blocks = getattr(model.model.diffusion_model, "blocks", None)
    state = TSTState(tau, len(blocks) if blocks is not None else 50)
    state.set_schedule(schedule)
    patched = model.clone()
    patched.add_wrapper_with_key(comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL, WRAPPER_KEY,
                                 partial(_forward_wrapper, state))
    options = dict(patched.model_options.get("transformer_options", {}))
    previous = options.get("optimized_attention_override")
    options["optimized_attention_override"] = partial(_override, state, previous)
    patched.model_options["transformer_options"] = options
    return patched, state
