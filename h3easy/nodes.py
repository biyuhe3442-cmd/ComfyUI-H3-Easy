"""ComfyUI nodes: H3 素材加载器 and H3 一键生成."""

from __future__ import annotations

import hashlib
from fractions import Fraction

import comfy.samplers
import folder_paths
from comfy_api.latest import InputImpl, Types, io

from . import media as media_io
from .media import NONE, REF_SLOTS, Media
from .pipeline import MODE_IMAGE, MODE_REFERENCE, UPSCALE_METHODS, UPSCALE_PIXEL, Settings, run

CATEGORY = "H3 Easy"
MediaType = io.Custom("H3_EASY_MEDIA")
UpscalerType = io.Custom("H3_LATENT_UPSCALER")

IMAGE_FIELDS = ["first_frame", "last_frame"] + [f"ref_image_{i}" for i in range(1, REF_SLOTS + 1)]
FILE_FIELDS = IMAGE_FIELDS + ["audio_file", "video_file"]


class H3EasyMediaLoader(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        images = [NONE] + media_io.list_inputs(["image"])
        audios = [NONE] + media_io.list_inputs(["audio", "video"])
        videos = [NONE] + media_io.list_inputs(["video"])

        def image_input(name, label, tooltip):
            return io.Combo.Input(name, options=images, default=NONE, display_name=label, tooltip=tooltip)

        inputs = [
            image_input("first_frame", "首帧图", "图文模式：视频从这张图开始。"),
            image_input("last_frame", "尾帧图", "图文模式：视频在这张图结束（多段时只作用于最后一段）。"),
        ]
        for i in range(1, REF_SLOTS + 1):
            inputs.append(image_input(f"ref_image_{i}", f"参考图{i}",
                                      f"参考模式：提示词里用 <Picture {i}> 指代这张图。"))
        inputs += [
            io.Combo.Input("audio_file", options=audios, default=NONE, display_name="音频",
                           tooltip="图文模式：锁定音频（引导口型，最终输出原音频）。参考模式：作为参考音频。"),
            io.Combo.Input("video_file", options=videos, default=NONE, display_name="视频",
                           tooltip="参考模式：画面作为参考视频（最多读取 15 秒）。图文模式：没有单独音频时，用它的音轨锁定音频。"),
        ]
        return io.Schema(
            node_id="H3EasyMediaLoader",
            display_name="H3 素材加载器",
            category=CATEGORY,
            description="可视化素材面板：首帧/尾帧、最多 9 张参考图、音频、视频。点击卡片或直接拖入文件，"
                        "打包后接到「H3 一键生成」。",
            inputs=inputs,
            outputs=[MediaType.Output(display_name="素材")],
        )

    @classmethod
    def validate_inputs(cls, **kwargs):
        for name in FILE_FIELDS:
            value = kwargs.get(name)
            if media_io.selected(value) and not folder_paths.exists_annotated_filepath(value):
                return f"找不到文件：{value}"
        return True

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        names = [kwargs.get(name, NONE) for name in FILE_FIELDS]
        return hashlib.sha256(media_io.file_signature(names).encode("utf-8")).hexdigest()

    @classmethod
    def execute(cls, **kwargs) -> io.NodeOutput:
        bundle = Media()
        if media_io.selected(kwargs.get("first_frame")):
            bundle.first_frame = media_io.load_image(kwargs["first_frame"])
        if media_io.selected(kwargs.get("last_frame")):
            bundle.last_frame = media_io.load_image(kwargs["last_frame"])
        for i in range(1, REF_SLOTS + 1):
            name = kwargs.get(f"ref_image_{i}")
            if media_io.selected(name):
                bundle.ref_images.append(media_io.load_image(name))
        if media_io.selected(kwargs.get("audio_file")):
            bundle.audio = media_io.load_audio(kwargs["audio_file"])
        if media_io.selected(kwargs.get("video_file")):
            bundle.video = media_io.load_video_frames(kwargs["video_file"])
            bundle.video_audio = media_io.load_video_audio(kwargs["video_file"])
        return io.NodeOutput(bundle)


class H3EasyGenerate(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3EasyGenerate",
            display_name="H3 一键生成",
            category=CATEGORY,
            description=(
                "MiniMax H3 音视频一键生成：图文模式（文生 / 首尾帧，可锁定音频）或参考模式（多图 / 视频参考）。"
                "支持多段续写长视频、第 1 段渐进加速和 TST 防闪烁，直接输出带声音的视频。"
            ),
            inputs=[
                io.Combo.Input("mode", options=[MODE_IMAGE, MODE_REFERENCE], default=MODE_IMAGE, display_name="模式"),
                io.String.Input("prompt", multiline=True, default="", display_name="提示词",
                                tooltip="多段时可用时间轴写法：[0-6s] 换行写第 1 段，[6-10s] 换行写第 2 段……；"
                                        "或用单独一行 --- 分隔每段；不分段则所有段共用。参考模式用 <Picture 1> 指代参考图1。"),
                io.Clip.Input("clip", display_name="文本编码器"),
                io.Vae.Input("video_vae", display_name="视频VAE"),
                io.Vae.Input("audio_vae", display_name="音频VAE"),
                io.Model.Input("image_model", optional=True, lazy=True, display_name="图文模型(fl2va)",
                               tooltip="图文模式使用。只用参考模式时可以不接。"),
                io.Model.Input("reference_model", optional=True, lazy=True, display_name="参考模型(ref2va)",
                               tooltip="参考模式使用。只用图文模式时可以不接。"),
                MediaType.Input("media", optional=True, display_name="素材"),
                UpscalerType.Input("learned_upscaler", optional=True, display_name="学习式upscaler",
                                   tooltip="可选：接 Upscaler-Plus 插件的「MiniMax H3 Latent Upscaler Provider (3D)」，第 1 段放大改用学习式模型。"),
                io.Int.Input("segments", default=1, min=1, max=20, display_name="段数",
                             tooltip="大于 1 时自动续写：每段接着上一段最后 39 帧（约 1.6 秒）生成。"),
                io.Float.Input("segment_seconds", default=6.0, min=3.5, max=14.0, step=0.5, display_name="每段秒数",
                               tooltip="会自动对齐到 H3 的音画同步网格（约 2.1 秒一档），实际时长见报告。"),
                io.Int.Input("width", default=1024, min=256, max=2048, step=32, display_name="宽"),
                io.Int.Input("height", default=576, min=256, max=2048, step=32, display_name="高"),
                io.Int.Input("steps", default=20, min=4, max=100, display_name="步数"),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, control_after_generate=True,
                             display_name="种子"),
                io.Boolean.Input("lock_audio", default=True, display_name="锁定音频",
                                 tooltip="仅图文模式：素材里有音频（或带音轨的视频）时，用它引导口型，最终输出原音频。"),
                io.Boolean.Input("progressive", default=True, display_name="渐进加速",
                                 tooltip="第 1 段前期先在小分辨率下生成再放大，省时间和显存。续写段始终全分辨率。"),
                io.Boolean.Input("tst", default=False, display_name="TST防闪烁",
                                 tooltip="实验功能：改善帧间闪烁和人物漂移，额外开销约几个百分点。"),
                io.Boolean.Input("low_vram", default=True, display_name="低显存模式",
                                 tooltip="各阶段之间卸载不用的模型、清理显存。16G 及以下建议开启。"),
                io.Combo.Input("sampler_name", options=comfy.samplers.KSampler.SAMPLERS, default="res_multistep",
                               display_name="采样器", advanced=True),
                io.Combo.Input("scheduler", options=comfy.samplers.KSampler.SCHEDULERS, default="simple",
                               display_name="调度器", advanced=True),
                io.Float.Input("progressive_scale", default=0.7, min=0.4, max=0.95, step=0.05,
                               display_name="加速缩放比例", advanced=True,
                               tooltip="前期小分辨率相对目标的比例。越小越快，但太小会丢细节。"),
                io.Float.Input("progressive_switch", default=0.35, min=0.1, max=0.9, step=0.05,
                               display_name="切换位置", advanced=True,
                               tooltip="在去噪进度的哪个位置切到全分辨率（未偏移时间坐标，越小低分辨率步数越多）。"),
                io.Combo.Input("upscale_method", options=UPSCALE_METHODS, default=UPSCALE_PIXEL,
                               display_name="放大方式", advanced=True),
                io.Float.Input("tst_strength", default=0.2, min=0.0, max=1.0, step=0.05,
                               display_name="TST强度", advanced=True),
                io.Combo.Input("ref_image_size", options=["match", "max"], default="match",
                               display_name="参考图尺寸", advanced=True,
                               tooltip="match：按输出画面大小缩放（快）；max：最高保真（慢很多）。"),
            ],
            outputs=[
                io.Video.Output(display_name="视频"),
                io.Image.Output(display_name="画面"),
                io.Audio.Output(display_name="音频"),
                io.String.Output(display_name="报告"),
            ],
        )

    @classmethod
    def check_lazy_status(cls, mode, image_model=None, reference_model=None, **kwargs):
        if mode == MODE_REFERENCE:
            return ["reference_model"] if reference_model is None else []
        return ["image_model"] if image_model is None else []

    @classmethod
    def validate_inputs(cls, width, height, **kwargs):
        if width % 32 or height % 32:
            return "宽和高必须是 32 的倍数"
        return True

    @classmethod
    def execute(cls, mode, prompt, clip, video_vae, audio_vae, segments, segment_seconds, width, height,
                steps, seed, lock_audio, progressive, tst, low_vram, sampler_name="res_multistep",
                scheduler="simple", progressive_scale=0.7, progressive_switch=0.35, upscale_method=UPSCALE_PIXEL,
                tst_strength=0.2, ref_image_size="match", image_model=None, reference_model=None, media=None,
                learned_upscaler=None) -> io.NodeOutput:
        model = reference_model if mode == MODE_REFERENCE else image_model
        if model is None:
            which = "参考模型(ref2va)" if mode == MODE_REFERENCE else "图文模型(fl2va)"
            raise ValueError(f"当前是{mode}，请把 {which} 接到「H3 一键生成」上")
        if learned_upscaler is not None and not callable(getattr(learned_upscaler, "upscale_clean_video", None)):
            raise ValueError("学习式upscaler 输入不是 MiniMax H3 Latent Upscaler Provider")
        settings = Settings(
            mode=mode, prompt=prompt, segments=segments, segment_seconds=segment_seconds,
            width=width, height=height, steps=steps, sampler_name=sampler_name, scheduler=scheduler,
            seed=seed, lock_audio=lock_audio, progressive=progressive, progressive_scale=progressive_scale,
            progressive_switch=progressive_switch, upscale_method=upscale_method, tst=tst,
            tst_strength=tst_strength, low_vram=low_vram, ref_image_size=ref_image_size,
        )
        result = run(settings, model, clip, video_vae, audio_vae, media, learned_upscaler)
        video = InputImpl.VideoFromComponents(
            Types.VideoComponents(images=result.images, audio=result.audio, frame_rate=Fraction(24)))
        return io.NodeOutput(video, result.images, result.audio, result.report)


NODES = [H3EasyMediaLoader, H3EasyGenerate]
