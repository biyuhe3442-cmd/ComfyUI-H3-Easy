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
        # Core allocates these buffers with torch.empty and a real checkpoint fills them; left as
        # is they hold whatever memory was there and occasionally turn the run into NaN
        dit = model.diffusion_model
        inv_freq = dit.rope.inv_freq
        inv_freq.copy_(1.0 / (10000 ** (torch.arange(inv_freq.numel(), dtype=torch.float32) / inv_freq.numel())))
        if hasattr(dit, "adaln_t_table"):
            dit.adaln_t_table.copy_(torch.randn(dit.adaln_t_table.shape, generator=g) * 0.02)
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
    # 480x300 first frame vs 512x320 output: same 1.6 ratio, no warning
    assert "比例不同" not in result.report
    # pixel upscale decoded the low-resolution clean estimate (352x256 -> latent 16x22)
    assert (1, 24, 27, 16, 22) in vae.decodes


def test_aspect_warning_for_portrait_first_frame(env):
    pipeline = env["pipeline"]
    from h3easy.media import Media
    assert pipeline.aspect_mismatch(torch.zeros(1, 1280, 720, 3), 1024, 576)
    assert not pipeline.aspect_mismatch(torch.zeros(1, 576, 1024, 3), 1344, 768)
    media = Media(first_frame=torch.rand(1, 640, 360, 3))
    result = pipeline.run(_settings(pipeline, progressive=False), env["model"], FakeClip(), FakeVideoVAE(),
                          FakeAudioVAE(), media)
    assert "首帧 360×640 和输出 512×320 比例不同，会被拉伸变形" in result.report


def test_three_segments_lock_audio_tst(env):
    pipeline = env["pipeline"]
    from h3easy.media import Media
    from h3easy import timing
    media = Media(first_frame=torch.rand(1, 320, 512, 3), last_frame=torch.rand(1, 320, 512, 3),
                  audios=[_audio(30.0)])
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
    assert torch.equal(result.audio["waveform"], media.audios[0]["waveform"][..., :result.audio["waveform"].shape[-1]])
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
                  videos=[torch.rand(30, 128, 160, 3)], video_audios=[_audio(1.25)], audios=[_audio(2.0)])
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


def test_generate_node_end_to_end(env):
    from h3easy.nodes import H3EasyGenerate
    from h3easy.pipeline import MODE_IMAGE, MODE_REFERENCE
    from h3easy.media import Media

    # lazy model inputs: only the (linked) model of the selected mode is requested
    assert H3EasyGenerate.check_lazy_status(mode=MODE_IMAGE, image_model=None, reference_model=None) == ["image_model"]
    assert H3EasyGenerate.check_lazy_status(mode=MODE_REFERENCE, image_model=None, reference_model=None) == ["reference_model"]
    assert H3EasyGenerate.check_lazy_status(mode=MODE_IMAGE, image_model=object()) == []
    # width/height may be linked (None during Core validation) or unaligned: no validation hook,
    # the pipeline snaps them to the 32-pixel grid instead
    assert "validate_inputs" not in H3EasyGenerate.__dict__

    out = H3EasyGenerate.execute(
        mode=MODE_IMAGE, prompt="hello", clip=FakeClip(), video_vae=FakeVideoVAE(), audio_vae=FakeAudioVAE(),
        segments=2, segment_seconds=3.5, width=512, height=320, steps=4, seed=5, lock_audio=True,
        progressive=True, tst=True, low_vram=True, sampler_name="euler", image_model=env["model"],
        media=Media(audios=[_audio(10.0)]))
    video, images, audio, report = out.args
    components = video.get_components()
    assert images.shape == (192, 320, 512, 3)
    assert components.images.shape[0] == 192
    assert float(components.frame_rate) == 24.0
    assert components.audio["waveform"].shape[-1] == round(192 / 24 * 44100)
    assert "锁定音频" in report

    with pytest.raises(ValueError, match="参考模型"):
        H3EasyGenerate.execute(
            mode=MODE_REFERENCE, prompt="x", clip=FakeClip(), video_vae=FakeVideoVAE(), audio_vae=FakeAudioVAE(),
            segments=1, segment_seconds=3.5, width=512, height=320, steps=4, seed=0, lock_audio=True,
            progressive=False, tst=False, low_vram=False, image_model=env["model"])


def test_media_loader_node(tmp_path):
    import av
    import numpy as np
    from PIL import Image
    import folder_paths
    from h3easy.media import NONE
    from h3easy.nodes import H3EasyMediaLoader

    Image.fromarray(np.zeros((40, 60, 3), dtype=np.uint8)).save(tmp_path / "a.png")
    rate = 16000
    wave = np.ascontiguousarray(np.zeros((1, rate * 2), dtype=np.float32))
    with av.open(str(tmp_path / "v.wav"), "w") as c:
        stream = c.add_stream("pcm_s16le", rate=rate, layout="mono")
        frame = av.AudioFrame.from_ndarray(wave, format="flt", layout="mono")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            c.mux(packet)
        for packet in stream.encode(None):
            c.mux(packet)
    with av.open(str(tmp_path / "c.mp4"), "w") as c:
        stream = c.add_stream("libx264", rate=12)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for i in range(24):
            img = np.full((48, 64, 3), i * 10, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                c.mux(packet)
        for packet in stream.encode(None):
            c.mux(packet)

    old = folder_paths.get_input_directory()
    folder_paths.set_input_directory(str(tmp_path))
    try:
        kwargs = {name: NONE for name in ["last_frame"] + [f"ref_image_{i}" for i in range(1, 10)]}
        kwargs.update({f"audio_{i}": NONE for i in range(1, 4)})
        kwargs.update({f"video_{i}": NONE for i in range(1, 4)})
        kwargs.update(first_frame="a.png", ref_image_2="a.png", audio_1="v.wav", audio_3="v.wav",
                      video_2="c.mp4")
        assert H3EasyMediaLoader.validate_inputs(**kwargs) is True
        assert "找不到文件" in H3EasyMediaLoader.validate_inputs(**dict(kwargs, ref_image_3="missing.png"))
        media = H3EasyMediaLoader.execute(**kwargs).args[0]
    finally:
        folder_paths.set_input_directory(old)
    assert media.first_frame.shape == (1, 40, 60, 3)
    assert media.last_frame is None
    assert len(media.ref_images) == 1
    assert len(media.audios) == 2
    assert media.audios[0]["sample_rate"] == rate and media.audios[0]["waveform"].shape[-1] == rate * 2
    assert media.lock_source is media.audios[0]
    # 2 s at 12 fps -> 48 frames at 24 fps, every source frame shown twice
    assert len(media.videos) == 1
    assert media.videos[0].shape == (48, 48, 64, 3)
    assert torch.equal(media.videos[0][0], media.videos[0][1])
    assert media.video_audios == [None]

    from h3easy.media import probe
    assert probe(str(tmp_path / "c.mp4"))["has_audio"] is False
    wav = probe(str(tmp_path / "v.wav"))
    assert wav["has_audio"] is True and abs(wav["duration"] - 2.0) < 0.05


def test_reference_mode_full_limits():
    """9 images, 3 videos (two with soundtracks) and 3 audios reach Core in H3's order."""
    from h3easy.conditioning import ConditioningBuilder
    from h3easy.media import Media
    from h3easy.timing import plan_segments

    class RecordingClip(FakeClip):
        def tokenize(self, text, images=None, minimax_ref_items=None, **kwargs):
            self.items = [item["type"] for item in (minimax_ref_items or [])]
            return super().tokenize(text, images=images, minimax_ref_items=minimax_ref_items)

    media = Media(ref_images=[torch.rand(1, 64, 64, 3) for _ in range(9)],
                  videos=[torch.rand(30, 64, 96, 3) for _ in range(3)],
                  video_audios=[_audio(1.2), None, _audio(1.0)],
                  audios=[_audio(1.0), _audio(2.0), _audio(0.5)])
    clip = RecordingClip()
    builder = ConditioningBuilder(clip, FakeVideoVAE(), FakeAudioVAE(), 512, 320, media)
    positive, _ = builder.reference_mode("x", plan_segments(1, 3.5)[0])
    # images, then each video preceded by its soundtrack label, then standalone audio
    assert clip.items == ["image"] * 9 + ["audio", "video", "video", "audio", "video"] + ["audio"] * 3
    kinds = [block["kind"] for block in positive[0][1]["minimax_refs"]]
    assert kinds == ["image"] * 9 + ["video_audio", "video", "video_audio"] + ["audio"] * 3


def test_image_mode_ignores_reference_media(env):
    pipeline = env["pipeline"]
    from h3easy.media import Media
    media = Media(ref_images=[torch.rand(1, 64, 64, 3)], videos=[torch.rand(30, 64, 96, 3)],
                  video_audios=[_audio(1.25)])
    result = pipeline.run(_settings(pipeline, progressive=False), env["model"], FakeClip(), FakeVideoVAE(),
                          FakeAudioVAE(), media)
    # no audio slot filled -> nothing locked, even though a video has a soundtrack
    assert "锁定音频" not in result.report
    assert "输出音频：H3 生成" in result.report
    assert "图文模式不使用参考图/参考视频" in result.report


def test_unaligned_size_is_snapped(env):
    pipeline = env["pipeline"]
    assert pipeline.snap_size(500) == 512 and pipeline.snap_size(336) == 320 and pipeline.snap_size(100) == 256
    result = pipeline.run(_settings(pipeline, width=500, height=330, progressive=False), env["model"], FakeClip(),
                          FakeVideoVAE(), FakeAudioVAE(), None)
    assert result.images.shape[1:3] == (320, 512)
    assert "500×330 → 512×320" in result.report


def test_lazy_model_input_only_requested_when_linked():
    from h3easy.nodes import H3EasyGenerate
    from h3easy.pipeline import MODE_IMAGE, MODE_REFERENCE

    # linked but not evaluated yet -> key present with None: ask for it
    assert H3EasyGenerate.check_lazy_status(mode=MODE_IMAGE, image_model=None) == ["image_model"]
    assert H3EasyGenerate.check_lazy_status(mode=MODE_REFERENCE, reference_model=None) == ["reference_model"]
    # nothing linked (or loader muted / bypassed) -> key absent: do not ask, execute() explains
    assert H3EasyGenerate.check_lazy_status(mode=MODE_IMAGE) == []
    assert H3EasyGenerate.check_lazy_status(mode=MODE_IMAGE, reference_model=None) == []
    # already evaluated
    assert H3EasyGenerate.check_lazy_status(mode=MODE_IMAGE, image_model=object()) == []


def test_missing_model_error_is_explained():
    from h3easy.nodes import H3EasyGenerate
    from h3easy.pipeline import MODE_IMAGE

    with pytest.raises(ValueError, match="图文模型\\(fl2va\\)」输入没有收到模型"):
        H3EasyGenerate.execute(mode=MODE_IMAGE, prompt="", clip=None, video_vae=None, audio_vae=None,
                               segments=1, segment_seconds=6.0, width=1024, height=576, steps=20, seed=0,
                               lock_audio=True, progressive=True, tst=False, low_vram=True)
