"""ComfyUI nodes: H3 素材加载器 and H3 一键生成."""

from __future__ import annotations

import hashlib
from fractions import Fraction

import comfy.samplers
import folder_paths
from comfy_api.latest import InputImpl, Types, io

from . import media as media_io
from .media import AUDIO_SLOTS, NONE, REF_SLOTS, VIDEO_SLOTS, Media
from .pipeline import MODE_IMAGE, MODE_REFERENCE, UPSCALE_METHODS, UPSCALE_PIXEL, Settings, run

CATEGORY = "H3 Easy"
MediaType = io.Custom("H3_EASY_MEDIA")
UpscalerType = io.Custom("H3_LATENT_UPSCALER")

IMAGE_FIELDS = ["first_frame", "last_frame"] + [f"ref_image_{i}" for i in range(1, REF_SLOTS + 1)]
AUDIO_FIELDS = [f"audio_{i}" for i in range(1, AUDIO_SLOTS + 1)]
VIDEO_FIELDS = [f"video_{i}" for i in range(1, VIDEO_SLOTS + 1)]
FILE_FIELDS = IMAGE_FIELDS + AUDIO_FIELDS + VIDEO_FIELDS


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
        for i in range(1, AUDIO_SLOTS + 1):
            inputs.append(io.Combo.Input(
                f"audio_{i}", options=audios, default=NONE, display_name=f"音频{i}",
                tooltip="图文模式：音频1 用于锁定音频（引导口型，最终输出原音频；也可以放带声音的视频）。"
                        "参考模式：参考音频，提示词里用 <Audio N> 指代（视频的音轨排在前面）。"))
        for i in range(1, VIDEO_SLOTS + 1):
            inputs.append(io.Combo.Input(
                f"video_{i}", options=videos, default=NONE, display_name=f"视频{i}",
                tooltip=f"参考模式：参考视频，提示词里用 <Video {i}> 指代；最多读取 15 秒，自带音轨一起作为参考。"))
        return io.Schema(
            node_id="H3EasyMediaLoader",
            display_name="H3 素材加载器",
            category=CATEGORY,
            description="可视化素材面板：首帧/尾帧、最多 9 张参考图、3 段参考视频、3 段音频（与官方 H3 上限一致）。"
                        "面板会跟随「H3 一键生成」的模式只显示用得到的素材；点击卡片或直接拖入文件。",
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
        for name in AUDIO_FIELDS:
            if media_io.selected(kwargs.get(name)):
                bundle.audios.append(media_io.load_audio(kwargs[name]))
        for name in VIDEO_FIELDS:
            if media_io.selected(kwargs.get(name)):
                bundle.videos.append(media_io.load_video_frames(kwargs[name]))
                bundle.video_audios.append(media_io.load_video_audio(kwargs[name]))
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
                             tooltip="大于 1 时自动续写，一次运行里按顺序完成：先完整生成第 1 段，再拿它最后 39 帧"
                                     "（约 1.6 秒）当开头生成第 2 段，依此类推，最后统一解码拼接。"),
                io.Float.Input("segment_seconds", default=6.0, min=3.5, max=14.0, step=0.5, display_name="每段秒数",
                               tooltip="会自动对齐到 H3 的音画同步网格（约 2.1 秒一档），实际时长见报告。"),
                io.Int.Input("width", default=1024, min=256, max=2048, step=32, display_name="宽",
                             tooltip="输出视频就是这个尺寸。首帧/尾帧比例不同时会居中裁切，不会拉伸。"),
                io.Int.Input("height", default=576, min=256, max=2048, step=32, display_name="高",
                             tooltip="输出视频就是这个尺寸。首帧/尾帧比例不同时会居中裁切，不会拉伸。"),
                io.Int.Input("steps", default=20, min=4, max=100, display_name="步数"),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, control_after_generate=True,
                             display_name="种子"),
                io.Boolean.Input("lock_audio", default=True, display_name="锁定音频",
                                 tooltip="仅图文模式：素材面板的「锁定音频」里放了音频时，用它引导口型，最终输出原音频。"),
                io.Boolean.Input("progressive", default=True, display_name="渐进加速",
                                 tooltip="只作用于第 1 段：前面的高噪步先用小分辨率跑，再放大到你设的分辨率跑完剩下的步数。"
                                         "默认 20 步时，前 13 步用 0.7 倍分辨率（例如 1024×576 → 704×416），后 7 步用 1024×576；"
                                         "8 步时是 5 + 3。续写段始终全分辨率。实际分配写在报告里。"),
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
                               tooltip="前期小分辨率相对你设的宽高的比例，对齐到 32 的倍数。0.7：1024×576 → 704×416。"
                                       "越小越快，但太小会丢细节。"),
                io.Float.Input("progressive_switch", default=0.35, min=0.1, max=0.9, step=0.05,
                               display_name="切换位置", advanced=True,
                               tooltip="什么时候切到全分辨率。数值越小，低分辨率跑的步数越多、越快。"
                                       "默认 0.35：20 步时前 13 步低分辨率。"),
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
    def check_lazy_status(cls, mode, **kwargs):
        # Only ask for the model this mode uses, and only when something is linked to it: an
        # unlinked input (or one whose loader is muted / bypassed) is absent from kwargs, and
        # asking for it makes ComfyUI fail with "needs input ... but there is no input".
        # execute() then explains what is missing instead.
        name = "reference_model" if mode == MODE_REFERENCE else "image_model"
        return [name] if name in kwargs and kwargs[name] is None else []

    @classmethod
    def execute(cls, mode, prompt, clip, video_vae, audio_vae, segments, segment_seconds, width, height,
                steps, seed, lock_audio, progressive, tst, low_vram, sampler_name="res_multistep",
                scheduler="simple", progressive_scale=0.7, progressive_switch=0.35, upscale_method=UPSCALE_PIXEL,
                tst_strength=0.2, ref_image_size="match", image_model=None, reference_model=None, media=None,
                learned_upscaler=None) -> io.NodeOutput:
        model = reference_model if mode == MODE_REFERENCE else image_model
        if model is None:
            if mode == MODE_REFERENCE:
                which, file = "参考模型(ref2va)", "minimax_h3_ref2va_*.safetensors"
            else:
                which, file = "图文模型(fl2va)", "minimax_h3_fl2va_*.safetensors"
            raise ValueError(
                f"现在是{mode}，但「H3 一键生成」的「{which}」输入没有收到模型。\n"
                f"请把加载 {file} 的模型加载节点连到这个输入；如果已经连了，检查那个加载节点是不是被"
                f"禁用（Ctrl+M）或绕过（Ctrl+B，节点变紫色）了。")
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
