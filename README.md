# ComfyUI-H3-Easy · MiniMax H3 一键生成

两个节点搞定 MiniMax H3 音视频生成：

- **H3 素材加载器**：可视化面板。首帧 / 尾帧、最多 9 张参考图、音频、视频，点卡片或直接拖文件进去。
- **H3 一键生成**：选模式、写提示词、点运行，直接出带声音的视频。

| 功能 | 说明 |
|---|---|
| 图文模式 | 文生视频；首帧 / 尾帧生视频 |
| 参考模式 | 多张参考图（提示词里写 `<Picture 1>`）+ 参考视频 + 参考音频 |
| 锁定音频 | 图文模式下上传音频：用它引导口型和节奏，**最终输出原音频**；不上传就由 H3 自己生成声音 |
| 长视频多段续写 | 每段精确接着上一段最后 39 帧（约 1.6 秒）继续生成，音画严格对齐 |
| 渐进加速 | 第 1 段前期在小分辨率下生成再放大，省时间和显存 |
| TST 防闪烁 | 实验功能：改善帧间闪烁、人物漂移 |
| 低显存模式 | 各阶段之间卸载用完的模型，适合 16G 显卡 |

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/biyuhe3442-cmd/ComfyUI-H3-Easy.git
```

重启 ComfyUI。不需要额外的 Python 依赖。

**ComfyUI 本体要更新到最新版。** 本插件直接调用 ComfyUI 自带的 MiniMax H3 节点和续写遮罩接口（ComfyUI PR #15375），旧版本没有这些功能。开发时验证用的是 2026-10-04 的 ComfyUI（commit `5c460d8`）。

## 下载模型

和 ComfyUI 官方 H3 模板用的是同一套文件（[Hugging Face](https://huggingface.co/Comfy-Org/MiniMax-H3) · [ModelScope 国内镜像](https://modelscope.cn/models/Comfy-Org/MiniMax-H3)）：

| 放到 | 文件 | 大小 | 用途 |
|---|---|---|---|
| `models/diffusion_models/` | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 19.5 GB | 图文模式 |
| `models/diffusion_models/` | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 19.5 GB | 参考模式（不用参考模式可以不下） |
| `models/text_encoders/` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 14.6 GB | 文本编码器 |
| `models/vae/` | `minimax_h3_video_vae_int8_convrot.safetensors` | 2.6 GB | 视频 VAE |
| `models/vae/` | `minimax_h3_audio_vae_fp32.safetensors` | 0.6 GB | 音频 VAE |
| `models/loras/`（可选） | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`（[lightx2v](https://huggingface.co/lightx2v/Minimax-h3-Turbo)） | 1.8 GB | 8 步提速 |

**可选：学习式放大。** 装 [Comfyui_Minimax_h3_latent_Upscaler-Plus](https://github.com/xmarre/Comfyui_Minimax_h3_latent_Upscaler-Plus)，并把 [H3 latent upscaler](https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler) 放进 `models/latent_upscale_models/`。然后把它的「MiniMax H3 Latent Upscaler Provider (3D)」接到「H3 一键生成」的「学习式upscaler」输入，第 1 段放大就会改用学习式模型。不装也能用，默认是像素放大。

## 快速开始

1. 把 `example_workflows/H3_Easy_basic.json` 拖进 ComfyUI。
2. 在各个模型节点的下拉框里选你本地的文件。
3. 写提示词，点运行。
4. 视频保存在 `ComfyUI/output/video/`，运行详情看「运行报告」节点。

示例工作流里有两个默认关闭的节点（紫色）：「参考模型 ref2va」和「Turbo LoRA」。选中节点按 **Ctrl+B** 打开或关闭。用不到的模型保持关闭，就不会被加载。

## H3 素材加载器

| 区域 | 图文模式 | 参考模式 |
|---|---|---|
| 首帧 / 尾帧 | 视频从首帧开始、在尾帧结束（多段时尾帧只作用于最后一段） | 不使用 |
| 参考图（最多 9 张） | 不使用 | 提示词里用 `<Picture 1>`…`<Picture 9>` 指代；点图上的标签可以复制 |
| 音频 | **锁定音频**：引导口型，输出原声 | 参考音频（音色 / 风格），输出 H3 生成的声音 |
| 视频 | 没有单独音频时，用它的音轨锁定音频 | 参考视频：画面 + 音轨。最多读取 15 秒，自动转成 24fps |

操作方式：
- **点卡片**选文件，或者直接把文件**拖到卡片上**。参考图可以一次多选或拖入多张。
- 卡片右上角的 × 是移除。删掉一张参考图后，后面的会自动往前补位，`<Picture N>` 的编号也跟着变。
- 音频可以直接试听，视频可以预览。

## H3 一键生成

### 常用参数

| 参数 | 默认 | 说明 |
|---|---|---|
| 模式 | 图文模式 | 图文模式用「图文模型」，参考模式用「参考模型」，只会加载当前模式需要的那个 |
| 段数 | 1 | 大于 1 时自动续写 |
| 每段秒数 | 6 | 会自动对齐到 H3 的音画网格，见下表 |
| 宽 / 高 | 1024 × 576 | 32 的倍数。H3 原生最大 1344×768（竖屏 768×1344） |
| 步数 | 20 | 打开 Turbo LoRA 时改成 8 |
| 锁定音频 | 开 | 只在图文模式、而且素材里有音频时生效 |
| 渐进加速 | 开 | 只作用于第 1 段 |
| TST防闪烁 | 关 | 实验功能 |
| 低显存模式 | 开 | 16G 及以下建议保持开启 |

### 高级参数

在节点的高级选项里，一般不用改：
- **采样器 / 调度器**：默认 `res_multistep` / `simple`，和官方模板一致。
- **加速缩放比例**：默认 0.7。越小越快，但太小会丢细节。
- **切换位置**：默认 0.35。数值越小，在低分辨率下跑的步数越多。
- **放大方式**：默认像素放大（低分辨率解码 → 放大 → 重新编码）。也可以选 latent 插值（最快，但可能有伪影）。
- **TST强度**：默认 0.2。
- **参考图尺寸**：match 按输出大小缩放；max 最高保真，但慢很多。

### 提示词写法

**时间轴（推荐多段时用）**：每段一节，标题单独占一行。标题上面的文字所有段共用。

```text
Realistic cinematic look, natural light.
[0-6s]
A young woman walks along a rainy street at night...
[6-12s]
She stops under a shop awning and smiles at the camera...
```

匹配规则：
- 小节数等于段数时，按顺序一一对应，不用管标题里写的时间是否精确。
- 小节数和段数不一致时，按时间重叠最多的那一节来匹配。

**分隔列表**：用单独一行 `---` 分开每段。段数比小节多时，多出来的段沿用最后一节。

**不分段**：所有段共用同一段提示词。

### 每段实际时长

为了让画面和声音在每段之间严格对齐，时长会吸附到 H3 的音画网格上（约 2.1 秒一档）：

| 每段秒数 | 第 1 段 | 之后每段新增 |
|---|---|---|
| 3.5 – 4.5 | 3.75 s | 4.25 s |
| 5 | 5.875 s | 4.25 s |
| 5.5 – 6.5 | 5.875 s | 6.375 s |
| 7 | 8 s | 6.375 s |
| 7.5 – 9 | 8 s | 8.5 s |
| 9.5 | 10.125 s | 8.5 s |
| 10 – 11 | 10.125 s | 10.625 s |
| 11.5 | 12.25 s | 10.625 s |
| 12 – 13 | 12.25 s | 12.75 s |
| 13.5 – 14 | 14.375 s | 12.75 s |

举例：段数 3、每段 6 秒 → 5.875 + 6.375 + 6.375 = **18.625 秒**。

每次运行的实际分段和时长都会写在「报告」输出里。

### 多段续写是怎么做的

- 第 2 段起，把上一段最后 39 帧的画面 latent，以及对应的 65 个音频 latent 帧，原样复制到新一段开头，标记为"保留"。用的是 ComfyUI 自带的 H3 遮罩续写接口。H3 只生成后面新的部分，接缝处不会重新生成。
- 锁定音频时，只保留画面；每段按绝对时间切出对应的那一截原音频来引导口型。
- 解码时，每段都会额外带上下一段开头的 5 个 latent 帧作为后文，避免 VAE 分段解码在接缝前 5 帧产生差异。所有段的声音拼成一条后一次解码，不会出现段与段之间的音量跳变。

### 16G 显卡建议

- 保持「低显存模式」开启。ComfyUI 会把放不下的模型部分放在内存里，需要较大内存（64G 比较稳）。
- 第一次先用 **1 段、1024×576** 确认能出片，再加段数和分辨率。
- 打开 Turbo LoRA，并把步数改成 8，速度会快很多。
- 渐进加速本身也会降低第 1 段前期的显存占用。

## 运行报告

「报告」输出会记录：
- 模式和用到的素材；
- 每段的时间范围和帧数；
- 渐进加速在哪一步切换；
- 每段的采样耗时；
- TST 的平均放大系数；
- 最终用的是原音频还是生成的声音。

出问题时请把报告和控制台里 `[H3 Easy]` 开头的行一起发出来。

## 已知限制

- **画质和速度还没有在真实 H3 模型上系统验证过。** 开发环境没有 GPU，测试是用 ComfyUI 自带的 H3 网络结构搭的迷你随机模型在 CPU 上跑完整流程，验证续写前缀精确保留、时长和音画对齐、渐进加速切换、解码拼接等机制，但看不了画面效果。
- TST 是按官方实现移植到 H3 的，属于实验功能，默认关闭。
- 参考模式不支持锁定音频，音频只作为参考。
- 续写段始终用全分辨率生成，渐进加速只作用于第 1 段。这样设计是因为续写段换分辨率容易在接缝处出问题。

## 开发与测试

```bash
python -m pytest tests/test_planning.py                       # 纯计算部分，不需要 ComfyUI
COMFYUI_PATH=/path/to/ComfyUI python -m pytest tests/        # 全部测试（迷你 H3 模型，CPU）
```

## 致谢与许可

本项目以 Apache-2.0 许可发布，见 [LICENSE](LICENSE)。借鉴的思路和代码来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：
- [Temporal State Transport](https://github.com/lytang63/temporal-state-transport)（MIT）
- [ComfyUI-H3-Continuum-Plus](https://github.com/xmarre/ComfyUI-H3-Continuum-Plus)（MIT）
- [MiniMax-H3-Flow-Aligned-Regenerate](https://github.com/xmarre/MiniMax-H3-Flow-Aligned-Regenerate)（Apache-2.0）
- [SelfLift 论文](https://arxiv.org/abs/2609.02036)
