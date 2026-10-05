import os
import sys

import pytest

COMFYUI = os.environ.get("COMFYUI_PATH")
pytestmark = pytest.mark.skipif(not COMFYUI, reason="set COMFYUI_PATH to a ComfyUI checkout")

if COMFYUI:
    sys.path.insert(0, COMFYUI)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch  # noqa: E402


def _qk(frames=8, rows=6, heads=2, dim=16, seed=0, scale=1.0):
    g = torch.Generator().manual_seed(seed)
    q = torch.randn(1, heads, frames * rows, dim, generator=g) * scale
    k = torch.randn(1, heads, frames * rows, dim, generator=g) * scale
    return q, k


def test_score_bounds_and_extremes():
    from h3easy.tst import balance_score
    q, k = _qk()
    score = balance_score(q, k, 8, 6)
    assert 0.0 <= score <= 0.25
    # uniform attention: one dominant eigenvalue, spectral entropy 0 -> no correction
    zeros = torch.zeros(1, 2, 48, 16)
    assert balance_score(zeros, zeros, 8, 6) == pytest.approx(0.0, abs=1e-6)
    # each frame attends only to itself: no temporal mixing -> no correction
    eye = torch.eye(8).repeat_interleave(6, dim=0)  # [48, 8]
    q = (eye * 50.0).reshape(1, 1, 48, 8).repeat(1, 2, 1, 1)
    assert balance_score(q, q, 8, 6) == pytest.approx(0.0, abs=1e-4)


def test_score_survives_lapack_failure(monkeypatch):
    from h3easy import tst

    def broken(_):
        raise RuntimeError("linalg.eigh: failed to converge")

    q, k = _qk(seed=3)
    expected = tst.balance_score(q, k, 8, 6)
    monkeypatch.setattr(torch.linalg, "eigvalsh", broken)
    assert tst.balance_score(q, k, 8, 6) == pytest.approx(expected, rel=1e-6)
    monkeypatch.setattr(torch.linalg, "svdvals", broken)
    assert tst.balance_score(q, k, 8, 6) == 0.0


def test_schedule_weights():
    from h3easy.tst import TSTState
    state = TSTState(0.2, total_layers=5)
    state.set_schedule([1.0, 0.8, 0.5, 0.2, 0.0])
    state.begin_forward(1.0)
    assert state.step_weight == pytest.approx(1.0)
    assert state.layer_weight() == pytest.approx(0.0)
    state.layer = 4
    assert state.layer_weight() == pytest.approx(1.0)
    state.begin_forward(0.2)
    assert state.step_weight == pytest.approx(0.0, abs=1e-9)
    assert state.layer == 0


def test_override_chains_previous_and_scales_video_rows():
    from h3easy import tst

    class Layout:
        segments = [(0, 4, "text"), (4, 10, "audio"), (10, 10 + 8 * 6, "video")]
        seq_len = 10 + 48
        signature = (4, 8, 6, 4, 3)  # latent 6x4 -> 3x2 = 6 rows per frame

    state = tst.TSTState(1.0, total_layers=1)
    state.step_weight = 1.0
    seen = []

    def previous(func, q, k, v, heads, *args, **kwargs):
        seen.append("previous")
        return func(q, k, v, heads, *args, **kwargs)

    def func(q, k, v, heads, *args, **kwargs):
        return torch.ones(1, q.shape[2], heads * q.shape[3])

    q, k = _qk(frames=8, rows=6)
    q = torch.cat([torch.zeros(1, 2, 10, 16), q], dim=2)
    k = torch.cat([torch.zeros(1, 2, 10, 16), k], dim=2)
    out = tst._override(state, previous, func, q, k, q, 2, transformer_options={"minimax_h3_layout": Layout()})
    assert seen == ["previous"]
    assert torch.equal(out[:, :10], torch.ones(1, 10, 32))
    scale = state.scales[-1]
    assert scale > 1.0
    assert torch.allclose(out[:, 10:], torch.full((1, 48, 32), scale))
    # token-refiner style call (text only) is passed through untouched
    out = tst._override(state, None, func, q[:, :, :4], k[:, :, :4], q[:, :, :4], 2,
                        transformer_options={"minimax_h3_layout": Layout()})
    assert torch.equal(out, torch.ones(1, 4, 32))
