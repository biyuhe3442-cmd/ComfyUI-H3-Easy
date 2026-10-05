# Third-party notices

## Temporal State Transport (TST)

`h3easy/tst.py` adapts the balance score and layer/step schedules of the official
TST implementation (`tst/core.py`) to MiniMax H3's packed attention.

- Source: https://github.com/lytang63/temporal-state-transport
- Paper: Temporal State Transport in Video Generation, arXiv:2609.08505

```
MIT License

Copyright (c) 2025 TST Authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ComfyUI-H3-Continuum-Plus (MIT)

The exact continuation design in `h3easy/continuation.py` and `h3easy/timing.py`
(39-frame / 65-audio-tick protected prefix through ComfyUI Core's native H3
denoise masks, keyframe and driving-audio rules) follows Continuum-Plus'
"Native Masked" continuation. No code was copied.

- Source: https://github.com/xmarre/ComfyUI-H3-Continuum-Plus (fork of
  https://github.com/ukr8b3g-cmyk/ComfyUI-H3-Continuum), MIT, Copyright (c) 2026 ukr8b3g-cmyk

## MiniMax-H3-Flow-Aligned-Regenerate (Apache-2.0)

Two ideas come from this project's documentation; no code was copied:

- decoding each segment with the next segment's first generated latent slots as
  right context (`h3easy/assemble.py`, from its "Continuum Decode Context");
- a progressive first segment that hands a lifted clean estimate to a fresh
  full-resolution sampler run, with the 0.70 scale / 0.35 handoff defaults
  (`h3easy/pipeline.py`).

- Source: https://github.com/xmarre/MiniMax-H3-Flow-Aligned-Regenerate, Copyright 2026 xmarre

## SelfLift

The pixel-anchor lift used by the default "像素放大" method (decode the
low-resolution clean estimate, upscale in pixel space, re-encode) is the
pixel-VAE anchor of SelfLift-zero, implemented from the paper:

- SelfLift: Accelerating Few-Step Diffusion via Self-Recovering Resolution
  Transition, arXiv:2609.02036

## ComfyUI

Conditioning, sampling and decoding call ComfyUI Core's own MiniMax H3 nodes and
APIs (GPL-3.0); this plugin does not redistribute ComfyUI code.

## YuNet face detector

`models/face_detection_yunet_2023mar.onnx` is the YuNet face detection model from the
OpenCV model zoo, used by `h3easy/faces.py` through OpenCV's `FaceDetectorYN`.

- Source: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- Paper: Wu et al., YuNet: A Tiny Millisecond-level Face Detector, Machine Intelligence Research 2023

```
MIT License

Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
