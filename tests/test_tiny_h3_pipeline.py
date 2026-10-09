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
    assert "首帧 360×640 和输出 512×320 比例不同：已居中裁切成 360×225" in result.report
    assert result.images.shape[1:3] == (320, 512)  # the output keeps the size that was set


def test_crop_to_aspect_keeps_the_middle():
    from h3easy.pipeline import crop_to_aspect
    portrait = torch.arange(1280 * 720, dtype=torch.float32).reshape(1, 1280, 720, 1)
    out = crop_to_aspect(portrait, 1024, 576)  # landscape output: trim top and bottom
    assert out.shape[1:3] == (405, 720)
    assert torch.equal(out[0, 0], portrait[0, (1280 - 405) // 2])
    landscape = torch.zeros(1, 540, 960, 3)
    assert crop_to_aspect(landscape, 576, 1024).shape[1:3] == (540, 304)  # portrait output: trim the sides
    assert crop_to_aspect(landscape, 1024, 576).shape[1:3] == (540, 960)


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
                                    progressive_continuation=True, prompt="<Picture 1> waves at <Picture 2>"),
                          env["model"], clip, FakeVideoVAE(), FakeAudioVAE(), media)
    assert result.images.shape[0] == 90 + 141 - 39
    assert torch.isfinite(result.images).all()
    assert "第 2 段渐进加速（实验）" in result.report
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
    video, images, audio, report, clips = out.args
    components = video.get_components()
    assert len(clips) == 1 and clips[0].get_components().images.shape[0] == 192
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
    builder = ConditioningBuilder(clip, FakeVideoVAE(), FakeAudioVAE(), 512, 320)
    positive, _ = builder.reference_mode("x", plan_segments(1, 3.5)[0].frames, media)
    # images, then each video preceded by its soundtrack label, then standalone audio
    assert clip.items == ["image"] * 9 + ["audio", "video", "video", "audio", "video"] + ["audio"] * 3
    kinds = [block["kind"] for block in positive[0][1]["minimax_refs"]]
    assert kinds == ["image"] * 9 + ["video_audio", "video", "video_audio"] + ["audio"] * 3


def test_reference_mode_sends_each_segment_only_its_references(env, monkeypatch):
    from comfy_extras import nodes_minimax_h3 as core_h3
    from h3easy.media import Media

    pipeline = env["pipeline"]
    calls = []
    original = core_h3.MiniMaxH3ReferenceToVideo.execute

    def spy(**kwargs):
        sizes = [tuple(img.shape[1:3]) for img in (kwargs["ref_images"] or {}).values()]
        calls.append((kwargs["prompt"], sizes, len(kwargs["ref_audios"] or {})))
        return original(**kwargs)

    monkeypatch.setattr(core_h3.MiniMaxH3ReferenceToVideo, "execute", spy)
    # sizes tell the images apart: picture 1 is 64x64, picture 2 64x128, picture 3 128x64
    media = Media(ref_images=[torch.rand(1, 64, 64, 3), torch.rand(1, 64, 128, 3), torch.rand(1, 128, 64, 3)],
                  audios=[_audio(1.0)])
    prompt = ("Cinematic.\n[0-4s]\n<Picture 1> walks alone.\n[4-8s]\n<Picture 1> meets <Picture 3>.\n"
              "[8-12s]\nAn empty street at dawn.\n[共用]\nWind.")
    result = pipeline.run(_settings(pipeline, mode=pipeline.MODE_REFERENCE, segments=3, prompt=prompt),
                          env["model"], FakeClip(), FakeVideoVAE(), FakeAudioVAE(), media)
    assert [c[0] for c in calls] == [
        "Cinematic.\n\n<Picture 1> walks alone.\n\nWind.",
        "Cinematic.\n\n<Picture 1> meets <Picture 2>.\n\nWind.",
        "Cinematic.\n\nAn empty street at dawn.\n\nWind.",
    ]
    assert [c[1] for c in calls] == [[(64, 64)], [(64, 64), (128, 64)], []]
    # the audio file is never named, so every segment keeps it
    assert [c[2] for c in calls] == [1, 1, 1]
    assert "第 2 段：图1、图3、音频1" in result.report
    assert "图2 没有在任何一段的提示词里提到" in result.report
    assert torch.isfinite(result.images).all()


def test_reference_mode_reports_unknown_tags(env):
    from h3easy.media import Media

    pipeline = env["pipeline"]
    media = Media(ref_images=[torch.rand(1, 64, 64, 3)])
    result = pipeline.run(_settings(pipeline, mode=pipeline.MODE_REFERENCE, prompt="<Picture 1> and <Picture 4>"),
                          env["model"], FakeClip(), FakeVideoVAE(), FakeAudioVAE(), media)
    assert "<Picture 4> 在素材加载器里没有对应素材" in result.report


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


def test_progressive_continuation_keeps_context(env, monkeypatch):
    """Experimental progressive continuation: low-res start, exact full-res context afterwards."""
    pipeline = env["pipeline"]
    from h3easy import continuation
    from h3easy.media import Media
    seen = {"prefix_calls": []}
    original_apply, original_restore = continuation.apply_prefix, continuation.restore_prefix

    def apply_spy(samples, video_ctx, audio_ctx):
        video, audio = continuation.split_av(samples)
        seen["prefix_calls"].append((tuple(video.shape), audio.clone(), audio_ctx))
        return original_apply(samples, video_ctx, audio_ctx)

    def restore_spy(samples, video_ctx, audio_ctx):
        video, audio = continuation.split_av(samples)
        seen["video_err"] = (video[:, :, :12] - video_ctx.to(video)).abs().max().item()
        seen["audio_err"] = (audio[..., :65] - audio_ctx.to(audio)).abs().max().item()
        return original_restore(samples, video_ctx, audio_ctx)

    monkeypatch.setattr(continuation, "apply_prefix", apply_spy)
    monkeypatch.setattr(continuation, "restore_prefix", restore_spy)
    result = pipeline.run(_settings(pipeline, segments=2, progressive=False, progressive_continuation=True),
                          env["model"], FakeClip(), FakeVideoVAE(), FakeAudioVAE(), Media())
    assert result.images.shape[0] == 90 + 141 - 39
    assert torch.isfinite(result.images).all()
    assert "第 2 段渐进加速（实验）：前" in result.report
    assert "第 1 段渐进加速" not in result.report  # the first-segment switch is independent
    # low-res stage (512x320 * 0.7 -> 352x256, 22x16 latent), then the full-res stage (32x20 latent)
    assert "前 4 步 352×256，后 2 步 512×320" in result.report
    assert "第 2 段放大：像素放大" in result.report
    shapes = [s for s, _, _ in seen["prefix_calls"]]
    assert shapes[0][-2:] == (16, 22) and shapes[1][-2:] == (20, 32)
    # the clean audio estimate handed to the full-res stage is in latent units: its context
    # part equals the source context (the sampler's audio scale was undone)
    _, x0_audio, audio_ctx = seen["prefix_calls"][1]
    assert (x0_audio[..., :65] - audio_ctx).abs().max().item() < 1e-3
    # the full-resolution stage itself kept the context (before the exact restore)
    assert seen["video_err"] < 1e-4, seen
    assert seen["audio_err"] < 1e-4, seen


def test_progressive_continuation_lock_audio_latent_method(env):
    pipeline = env["pipeline"]
    from h3easy.media import Media
    settings = _settings(pipeline, segments=3, progressive=True, progressive_continuation=True,
                         upscale_method=pipeline.UPSCALE_LATENT)
    result = pipeline.run(settings, env["model"], FakeClip(), FakeVideoVAE(), FakeAudioVAE(),
                          Media(audios=[_audio(10.0)]))
    assert result.images.shape[0] == 90 + 2 * (141 - 39)
    assert torch.isfinite(result.images).all()
    for i in (2, 3):
        assert f"第 {i} 段渐进加速（实验）" in result.report
    assert "输出音频：原音频" in result.report


SHOT_SHEET = """# EP01 出片清单

**一共：** 3 个镜头　**画幅：** 9:16

SHOT 01
Duration: 3.5s
Mode: Ref2VA（参考模式：接角色图、场景图）
References:
<Picture 1> 沈烬 —— 第 1 张接 `沈烬.png`
<Picture 2> 断月台 —— 第 2 张接 `断月台.png`
H3 Prompt:
```text
<Picture 1> walks onto <Picture 2>.
```

SHOT 02
Duration: 2s
Mode: Ref2VA（参考模式：接角色图、场景图）
References:
<Picture 1> 绯璃（角色参考板）
<Audio 1> 她的声音：`voice.wav`
接上一镜：续写
H3 Prompt:
```text
<Picture 1> turns around and speaks in the voice of <Audio 1>.
```

SHOT 03
Duration: 3.5s
Mode: I2VA（首帧模式：从这张图开始）
References:
<Picture 1> 首帧图 —— `窗边.png`
接上一镜：续写
H3 Prompt:
```text
The woman shown in <Picture 1> looks up.
```
"""


def _shot_list_inputs(folder):
    """The files SHOT_SHEET names; image sizes tell them apart."""
    import av
    import numpy as np
    from PIL import Image

    (folder / "参考图").mkdir()
    for name, (height, width) in {"沈烬.png": (64, 64), "参考图/断月台.jpg": (64, 128), "绯璃.PNG": (128, 64),
                                  "窗边.png": (640, 360), "voice.png": (32, 32)}.items():
        Image.fromarray(np.zeros((height, width, 3), dtype=np.uint8)).save(folder / name)
    with av.open(str(folder / "voice.wav"), "w") as container:
        stream = container.add_stream("pcm_s16le", rate=16000, layout="mono")
        frame = av.AudioFrame.from_ndarray(np.zeros((1, 16000), dtype=np.float32), format="flt", layout="mono")
        frame.sample_rate = 16000
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def _shot_list_kwargs(env, **overrides):
    from h3easy.pipeline import MODE_IMAGE
    base = dict(mode=MODE_IMAGE, prompt=SHOT_SHEET, clip=FakeClip(), video_vae=FakeVideoVAE(),
                audio_vae=FakeAudioVAE(), segments=1, segment_seconds=6.0, width=512, height=320, steps=6, seed=3,
                lock_audio=True, progressive=True, tst=False, low_vram=False, sampler_name="euler",
                image_model=env["model"], reference_model=env["model"])
    base.update(overrides)
    return base


def test_shot_list_runs_each_card_with_its_own_media(env, tmp_path, monkeypatch):
    import folder_paths
    from comfy_extras import nodes_minimax_h3 as core_h3
    from h3easy.nodes import H3EasyGenerate
    from h3easy.pipeline import MODE_IMAGE

    calls = []
    original = core_h3.MiniMaxH3ReferenceToVideo.execute

    def spy(**kwargs):
        sizes = [tuple(img.shape[1:3]) for img in (kwargs["ref_images"] or {}).values()]
        calls.append((kwargs["prompt"], sizes, len(kwargs["ref_audios"] or {}), kwargs["length"]))
        return original(**kwargs)

    monkeypatch.setattr(core_h3.MiniMaxH3ReferenceToVideo, "execute", spy)
    _shot_list_inputs(tmp_path)
    old = folder_paths.get_input_directory()
    folder_paths.set_input_directory(str(tmp_path))
    try:
        # both models are asked for: the list has reference shots and a first-frame shot
        assert H3EasyGenerate.check_lazy_status(mode=MODE_IMAGE, prompt=SHOT_SHEET, image_model=None,
                                                reference_model=None) == ["image_model", "reference_model"]
        kwargs = _shot_list_kwargs(env)
        video, images, audio, report, clips = H3EasyGenerate.execute(**kwargs).args

        # a changed file under the same name runs the list again; an ordinary prompt has nothing to watch
        before = H3EasyGenerate.fingerprint_inputs(prompt=SHOT_SHEET)
        os.utime(tmp_path / "沈烬.png", (1, 1))
        assert H3EasyGenerate.fingerprint_inputs(prompt=SHOT_SHEET) != before
        assert H3EasyGenerate.fingerprint_inputs(prompt="a cat") == H3EasyGenerate.fingerprint_inputs()
    finally:
        folder_paths.set_input_directory(old)

    # each card got its own files, in its own order, with its prompt untouched
    assert calls == [
        ("<Picture 1> walks onto <Picture 2>.", [(64, 64), (64, 128)], 0, 90),
        ("<Picture 1> turns around and speaks in the voice of <Audio 1>.", [(128, 64)], 1, 90),
    ]
    # 3.75 s, then 51 new frames continuing it, then a cut to a 3.75 s first-frame shot
    assert images.shape == (90 + 51 + 90, 320, 512, 3)
    assert torch.isfinite(images).all()
    assert [clip.get_components().images.shape[0] for clip in clips] == [90, 51, 90]
    assert audio["waveform"].shape[-1] == round(231 / 24 * 32000)
    assert clips[1].get_components().audio["waveform"].shape[-1] == 51 * 32000 // 24
    assert video.get_components().images.shape[0] == 231
    # only the shot that is continued is decoded with the next one's right context
    decodes = [shape[2] for shape in kwargs["video_vae"].decodes if shape[3] == 20]
    assert decodes == [27 + 5, 27, 27]

    assert "出片清单：3 个镜头，总时长 9.62s" in report
    assert "镜头 1：0.00–3.75s，参考模式，开头，清单 3.5 秒 → 实际 3.75 秒，素材：沈烬.png、参考图/断月台.jpg" in report
    assert "镜头 2：3.75–5.88s，参考模式，续写，清单 2 秒 → 实际 2.12 秒，素材：绯璃.PNG、voice.wav" in report
    assert "镜头 3：5.88–9.62s，首帧模式，硬切" in report
    assert "镜头 3 和上一个镜头的模式不同，不能续写，按硬切处理" in report
    assert "镜头 3 首帧 360×640 和输出 512×320 比例不同" in report
    assert "清单写的画幅是 9:16，节点设的输出是 512×320" in report
    # every shot that starts with a cut gets the low-resolution start
    assert "镜头 1 渐进加速：" in report and "镜头 3 渐进加速：" in report and "镜头 2 渐进加速" not in report
    assert "镜头 2 采样完成" in report and "镜头 3 解码完成" in report


def test_shot_list_problems_are_reported_before_any_work(env, tmp_path):
    import folder_paths
    from h3easy.nodes import H3EasyGenerate

    old = folder_paths.get_input_directory()
    folder_paths.set_input_directory(str(tmp_path))
    try:
        with pytest.raises(ValueError, match="素材没找到") as error:
            H3EasyGenerate.execute(**_shot_list_kwargs(env))
    finally:
        folder_paths.set_input_directory(old)
    # everything that is missing in one message
    for line in ("镜头 1 的 <Picture 1>：沈烬.png", "镜头 1 的 <Picture 2>：断月台.png", "镜头 2 的 <Picture 1>：绯璃",
                 "镜头 2 的 <Audio 1>：voice.wav", "镜头 3 的 <Picture 1>：窗边.png"):
        assert line in str(error.value)

    with pytest.raises(ValueError, match="出片清单里有参考模式的镜头，但「H3 一键生成」的「参考模型"):
        H3EasyGenerate.execute(**_shot_list_kwargs(env, reference_model=None))
    with pytest.raises(ValueError, match="出片清单里有读不懂的地方：\n镜头 7：没有读到时长"):
        H3EasyGenerate.execute(**_shot_list_kwargs(env, prompt="SHOT 07\nMode: Ref2VA\nH3 Prompt:\nhello"))
    # cards that cannot be found must not turn the whole list into one prompt
    with pytest.raises(ValueError, match="提示词像是出片清单，但没有读到镜头卡"):
        H3EasyGenerate.execute(**_shot_list_kwargs(env, prompt="镜头一\nDuration: 5s\nH3 Prompt:\n```text\nhi\n```"))


def test_shot_list_files_are_found_by_name(tmp_path):
    import folder_paths
    from h3easy import media

    _shot_list_inputs(tmp_path)
    (tmp_path / "参考图" / "沈烬.png").write_bytes((tmp_path / "沈烬.png").read_bytes())
    old = folder_paths.get_input_directory()
    folder_paths.set_input_directory(str(tmp_path))
    try:
        files = media.input_files()
        assert "参考图/断月台.jpg" in files
        # the same name in two places: the one at the top of the input folder
        assert media.find_input("沈烬.png", ["image"], files) == "沈烬.png"
        # another extension, another case, or no extension at all
        assert media.find_input("断月台.png", ["image"], files) == "参考图/断月台.jpg"
        assert media.find_input("绯璃", ["image"], files) == "绯璃.PNG"
        # an image never stands in for audio
        assert media.find_input("voice", ["audio", "video"], files) == "voice.wav"
        assert media.find_input("voice", ["image"], files) == "voice.png"
        assert media.find_input("../沈烬.png", ["image"], files) == "沈烬.png"
        assert media.find_input("没有这张图.png", ["image"], files) is None
    finally:
        folder_paths.set_input_directory(old)


@pytest.fixture(autouse=True)
def _own_user_folder(tmp_path):
    """Shot lists keep their finished shots under the user folder: stay out of the real one."""
    import folder_paths
    old = folder_paths.get_user_directory()
    folder_paths.set_user_directory(str(tmp_path / "user"))
    yield
    folder_paths.set_user_directory(old)


def test_shot_list_only_samples_what_changed(env, tmp_path, monkeypatch):
    import folder_paths
    from h3easy import pipeline
    from h3easy.nodes import H3EasyGenerate

    sampled = []
    original = pipeline._sample

    def spy(model, positive, latent, sigmas, sampler, seed, **kwargs):
        sampled.append(seed)
        return original(model, positive, latent, sigmas, sampler, seed, **kwargs)

    monkeypatch.setattr(pipeline, "_sample", spy)
    _shot_list_inputs(tmp_path)
    old = folder_paths.get_input_directory()
    folder_paths.set_input_directory(str(tmp_path))

    def run(**overrides):
        sampled.clear()
        out = H3EasyGenerate.execute(**_shot_list_kwargs(env, progressive=False, **overrides)).args
        return out[1], out[3], len(sampled)

    try:
        first, report, count = run()
        assert count == 3 and "沿用上次的结果" not in report
        # a shot list does not go by the node's seed: the second run has nothing left to sample
        again, report, count = run(seed=99)
        assert count == 0 and report.count("沿用上次的结果") == 3
        assert torch.equal(again, first)
        # re-roll the last shot: the other two stay exactly as they were
        third, report, count = run(shot_versions="3:2")
        assert count == 1 and "镜头 3 采样完成" in report and report.count("沿用上次的结果") == 2
        assert torch.equal(third[:141], first[:141]) and not torch.equal(third[141:], first[141:])
        # re-rolling a shot also redoes the shot that continues it, but not the one after the cut
        _, report, count = run(shot_versions="1:2")
        assert count == 2 and "镜头 3 沿用上次的结果" in report
        # back to the first takes: they are all still there
        back, _, count = run()
        assert count == 0 and torch.equal(back, first)
        # a changed prompt or a changed file redoes just that shot
        assert run(prompt=SHOT_SHEET.replace("looks up", "looks down"))[2] == 1
        os.utime(tmp_path / "窗边.png", (5, 5))
        assert run()[2] == 1
        # so does a different sampling setting, for every shot
        assert run(steps=5)[2] == 3
    finally:
        folder_paths.set_input_directory(old)


def test_shot_store_round_trip_and_pruning(monkeypatch):
    from h3easy import shotcache

    assert shotcache.key("a", 1, [2.0]) == shotcache.key("a", 1, [2.0]) != shotcache.key("a", 1, [2.5])
    assert shotcache.source(None) == [] and shotcache.load(shotcache.key("nothing")) is None
    video, audio = torch.rand(1, 24, 7, 4, 6), torch.rand(1, 32, 2, 50)
    shotcache.save("one", video, audio)
    loaded = shotcache.load("one")
    assert torch.equal(loaded[0], video) and torch.equal(loaded[1], audio)

    size = os.path.getsize(shotcache._path("one"))
    monkeypatch.setattr(shotcache, "LIMIT_BYTES", int(size * 2.5))
    os.utime(shotcache._path("one"), (10, 10))
    shotcache.save("two", video, audio)
    os.utime(shotcache._path("two"), (20, 20))
    shotcache.save("three", video, audio)
    # room for two: the one used longest ago went
    assert shotcache.load("one") is None
    assert shotcache.load("two") is not None and shotcache.load("three") is not None


def test_stopped_shot_list_resumes_where_it_stopped(env, tmp_path, monkeypatch):
    import folder_paths
    from h3easy import pipeline
    from h3easy.nodes import H3EasyGenerate

    calls = []
    original = pipeline._sample

    def stop_at_third(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("stopped")
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_sample", stop_at_third)
    _shot_list_inputs(tmp_path)
    old = folder_paths.get_input_directory()
    folder_paths.set_input_directory(str(tmp_path))
    try:
        with pytest.raises(RuntimeError, match="stopped"):
            H3EasyGenerate.execute(**_shot_list_kwargs(env, progressive=False))
        report = H3EasyGenerate.execute(**_shot_list_kwargs(env, progressive=False)).args[3]
    finally:
        folder_paths.set_input_directory(old)
    # the two finished shots were kept; only the third was sampled the second time
    assert len(calls) == 4
    assert "镜头 1 沿用上次的结果" in report and "镜头 2 沿用上次的结果" in report and "镜头 3 采样完成" in report
