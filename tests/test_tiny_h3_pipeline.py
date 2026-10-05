"""End-to-end pipeline test on a tiny random MiniMax H3 built from ComfyUI Core.

Runs the real Core H3 DiT (2 layers, random weights), Core conditioning nodes,
Core samplers and native denoise masks on CPU. Text encoder and VAEs are small
stand-ins with the right shapes. Requires a ComfyUI checkout:

    COMFYUI_PATH=/path/to/ComfyUI python -m pytest tests/test_tiny_h3_pipeline.py
"""

import os
import sys

import pytest

COMFYUI = os.environ.get("COMFYUI_PATH")
pytestmark = pytest.mark.skipif(not COMFYUI, reason="set COMFYUI_PATH to a ComfyUI checkout")

if COMFYUI:
    sys.path.insert(0, COMFYUI)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import comfy.cli_args
    comfy.cli_args.args.cpu = True

import torch  # noqa: E402

TEXT_DIM = 64
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)


def _slots_for_frames(frames):
    slots, total = 0, 0
    while total < frames:
        total += FRAME_PER_TOKEN[slots % 5]
        slots += 1
    assert total == frames, frames
    return slots


class FakeClip:
    def __init__(self):
        self.calls = 0

    def tokenize(self, text, images=None, minimax_ref_items=None, **kwargs):
        return {"text": text, "n_images": len(images or []), "refs": len(minimax_ref_items or [])}

    def encode_from_tokens_scheduled(self, tokens):
        self.calls += 1
        g = torch.Generator().manual_seed(len(tokens["text"]) + 7 * tokens["n_images"] + 13 * tokens["refs"])
        return [[torch.randn(1, 12, TEXT_DIM, generator=g), {}]]


class FakeVideoVAE:
    """Linear stand-in: 16x spatial, H3 temporal slot pattern."""

    def __init__(self):
        g = torch.Generator().manual_seed(3)
        self.proj = torch.randn(24, 3, generator=g) * 0.1
        self.decodes = []

    def encode(self, images):
        images = images[..., :3].float()
        frames, h, w = images.shape[0], images.shape[1] // 16, images.shape[2] // 16
        slots = 1 if frames == 1 else _slots_for_frames(frames)
        pooled = torch.nn.functional.adaptive_avg_pool2d(images.movedim(-1, 1), (h, w))  # [F,3,h,w]
        idx = torch.linspace(0, frames - 1, slots).round().long()
        picked = pooled[idx]  # [T,3,h,w]
        latent = torch.einsum("ck,tkhw->cthw", self.proj, picked)
        return latent.unsqueeze(0)

    def decode(self, latent):
        self.decodes.append(tuple(latent.shape))
        t, h, w = latent.shape[2], latent.shape[3], latent.shape[4]
        frames = sum(FRAME_PER_TOKEN[i % 5] for i in range(t))
        rgb = torch.einsum("kc,cthw->thwk", self.proj.T, latent[0].float())
        rgb = torch.sigmoid(rgb)
        reps = torch.tensor([FRAME_PER_TOKEN[i % 5] for i in range(t)])
        rgb = rgb.repeat_interleave(reps, dim=0)[:frames]
        rgb = rgb.repeat_interleave(16, dim=1).repeat_interleave(16, dim=2)
        return rgb.unsqueeze(0)


class FakeAudioVAE:
    audio_sample_rate = 32000

    def encode(self, waveform):  # [1, L, C]
        ticks = max(1, round(waveform.shape[1] / 800))
        return torch.zeros(1, 32, 2, ticks) + waveform.mean()

    def decode(self, latent):  # [1,32,2,T] -> [1, L, 2]
        samples = latent.shape[-1] * 800
        t = torch.arange(samples).float() / self.audio_sample_rate
        tone = torch.sin(2 * torch.pi * 220 * t)
        return torch.stack([tone, tone], dim=-1).unsqueeze(0)


def _tiny_model():
    import comfy.model_patcher
    import comfy.supported_models as sm

    unet_config = {
        "image_model": "minimax_h3", "hidden_size": 64, "num_layers": 2, "token_refiner_num_layers": 1,
        "num_attention_heads": 2, "attention_head_dim": 128, "ffn_hidden_size": 128, "text_dim": TEXT_DIM,
        "time_embed_hidden_size": 64, "time_embed_dim": 32,
    }
    config = sm.MiniMaxH3(unet_config)
    config.set_inference_dtype(torch.float32, None)
    model = config.get_model({}, device="cpu")
    g = torch.Generator().manual_seed(0)
    with torch.no_grad():
        for p in model.parameters():
            p.copy_(torch.randn(p.shape, generator=g) * 0.02)
    model.to(torch.float32)
    return comfy.model_patcher.ModelPatcher(model, load_device=torch.device("cpu"), offload_device=torch.device("cpu"))


@pytest.fixture(scope="module")
def env():
    from h3easy import pipeline
    return {"model": _tiny_model(), "pipeline": pipeline}


def _settings(pipeline, **overrides):
    base = dict(mode=pipeline.MODE_IMAGE, prompt="a cat", segments=1, segment_seconds=3.5, width=512,
                height=320, steps=6, sampler_name="euler", scheduler="simple", seed=1, low_vram=False)
    base.update(overrides)
    return pipeline.Settings(**base)


def _audio(seconds, rate=44100):
    t = torch.arange(int(seconds * rate)).float() / rate
    wave = torch.sin(2 * torch.pi * 330 * t)
    return {"waveform": torch.stack([wave, wave]).unsqueeze(0), "sample_rate": rate}


def test_single_segment_progressive(env):
    pipeline = env["pipeline"]
    from h3easy.media import Media
    media = Media(first_frame=torch.rand(1, 300, 480, 3))
    vae = FakeVideoVAE()
    result = pipeline.run(_settings(pipeline, progressive=True), env["model"], FakeClip(), vae, FakeAudioVAE(), media)
    assert result.images.shape == (90, 320, 512, 3)
    assert torch.isfinite(result.images).all()
    assert result.audio["waveform"].shape[-1] == round(90 / 24 * 32000)
    assert "渐进加速" in result.report
    # pixel upscale decoded the low-resolution clean estimate (352x256 -> latent 16x22)
    assert (1, 24, 27, 16, 22) in vae.decodes


def test_three_segments_lock_audio_tst(env):
    pipeline = env["pipeline"]
    from h3easy.media import Media
    from h3easy import timing
    media = Media(first_frame=torch.rand(1, 320, 512, 3), last_frame=torch.rand(1, 320, 512, 3),
                  audio=_audio(30.0))
    clip = FakeClip()
    vae = FakeVideoVAE()
    settings = _settings(pipeline, segments=3, segment_seconds=4.0, progressive=True,
                         upscale_method=pipeline.UPSCALE_LATENT, tst=True, tst_strength=0.3,
                         prompt="[0-4s]\nA\n[4-8s]\nB\n[8-12s]\nC")
    result = pipeline.run(settings, env["model"], clip, vae, FakeAudioVAE(), media)
    segs = timing.plan_segments(3, 4.0)
    total = timing.total_frames(segs)
    assert result.images.shape[0] == total
    assert result.audio["sample_rate"] == 44100
    assert result.audio["waveform"].shape[-1] == round(total / 24 * 44100)
    # locked audio is the source waveform, untouched
    assert torch.equal(result.audio["waveform"], media.audio["waveform"][..., :result.audio["waveform"].shape[-1]])
    assert "TST" in result.report and "平均放大系数" in result.report
    # every segment but the last decoded with 5 extra right-context slots
    video_decodes = [s for s in vae.decodes if s[3] == 20]
    assert [d[2] for d in video_decodes] == [s.video_t + 5 for s in segs[:-1]] + [segs[-1].video_t]


def test_continuation_prefix_is_exact(env, monkeypatch):
    """The sampler keeps the protected prefix (before our exact restore)."""
    pipeline = env["pipeline"]
    from h3easy import continuation
    from h3easy.media import Media
    seen = {}
    original_restore = continuation.restore_prefix

    def spy(samples, video_ctx, audio_ctx):
        video, audio = continuation.split_av(samples)
        seen["video_err"] = (video[:, :, :12] - video_ctx.to(video)).abs().max().item()
        if audio_ctx is not None:
            seen["audio_err"] = (audio[..., :65] - audio_ctx.to(audio)).abs().max().item()
        return original_restore(samples, video_ctx, audio_ctx)

    monkeypatch.setattr(continuation, "restore_prefix", spy)
    result = pipeline.run(_settings(pipeline, segments=2, progressive=False), env["model"], FakeClip(),
                          FakeVideoVAE(), FakeAudioVAE(), Media())
    assert result.images.shape[0] == 90 + 141 - 39
    assert seen["video_err"] < 1e-4, seen
    assert seen["audio_err"] < 1e-4, seen


def test_reference_mode(env):
    pipeline = env["pipeline"]
    from h3easy.media import Media
    media = Media(ref_images=[torch.rand(1, 256, 256, 3), torch.rand(1, 300, 200, 3)],
                  video=torch.rand(30, 128, 160, 3), video_audio=_audio(1.25), audio=_audio(2.0))
    clip = FakeClip()
    result = pipeline.run(_settings(pipeline, mode=pipeline.MODE_REFERENCE, segments=2, progressive=True,
                                    prompt="<Picture 1> waves at <Picture 2>"),
                          env["model"], clip, FakeVideoVAE(), FakeAudioVAE(), media)
    assert result.images.shape[0] == 90 + 141 - 39
    # same prompt + different segment lengths -> one encode per distinct length
    assert clip.calls == 2
    assert "参考模式：音频只作为参考" in result.report


def test_learned_upscaler_is_used(env):
    pipeline = env["pipeline"]
    calls = []

    class Provider:
        def upscale_clean_video(self, video, *, target_h, target_w):
            calls.append((tuple(video.shape), target_h, target_w))
            return torch.nn.functional.interpolate(video, size=(video.shape[2], target_h, target_w))

    pipeline.run(_settings(pipeline, progressive=True), env["model"], FakeClip(), FakeVideoVAE(), FakeAudioVAE(),
                 None, learned_upscaler=Provider())
    assert calls == [((1, 24, 27, 16, 22), 20, 32)]
