# 本地识别后端

在“识别与语言 → 本地模型”选择，未就绪时点击“准备模型与环境并应用”。准备成功才保存并重启，取消/下载失败保留原设置。模型、运行时与缓存不进入 Git。

| 选项 | 运行方式 | 草稿更新 | 当前预读 |
| --- | --- | --- | --- |
| Whisper 系列 | Tiger 自带 faster-whisper/CTranslate2 | 语音停顿封存前段，尾窗解码 | 支持 |
| Kotoba-Whisper v2.0 | 同一 faster-whisper 运行库；日本电视音频训练的日语蒸馏模型 | 语音停顿封存前段，尾窗解码 | 支持 |
| Qwen3-ASR 0.6B / 1.7B，Q8 | 项目管理的 Windows 原生 audio.cpp 服务 | 语音停顿封存前段，尾窗解码 | 不支持，继续实时 |
| Voxtral Mini 4B Realtime，Q4_K | 同一 audio.cpp 服务，持续 raw PCM 输入 | 原生有状态流式 | 不支持，继续实时 |
| ReazonSpeech K2 v2，INT8 | 项目 .venv 的 sherpa-onnx CPU 工作进程 | 语音停顿封存前段，尾窗解码 | 不支持，继续实时 |

Kotoba 与 ReazonSpeech 只允许日语或 Default；ReazonSpeech 的 Default 也按日语处理。日语注音继续由 Sudachi 生成，显示端仍可选择独立浮窗、Luna 或两者。Whisper 幻觉词表仅作用于 Whisper/Kotoba，切换其他模型不会清空已编辑词表。

## 推理设备

Qwen/Voxtral 提供 CUDA 13.3、Vulkan 与 CPU 选项，可指定设备编号。自动模式优先独立显卡，避免双显卡笔记本的 Vulkan 0 号核显被误选。设备编号依后端独立编号；CUDA 0 与 Vulkan 0 未必是同一显卡。

模型速度和显存需求随设备、驱动和输入长度变化。选择后可先播放一小段日语音频，确认更新速度适合自己的电脑。模型文件大小不等于运行时显存峰值。

## 字幕如何更新

Whisper、Kotoba、Qwen 和 Reazon 使用增长或滚动音频窗解码，确认前段后继续识别尾部；Voxtral 使用有状态实时接口，只传输新增音频。它们都能逐步更新字幕，但不代表所有模型都实现了编码器或 KV 缓存复用。

Voxtral 的适配通过同一个 HTTP/1.1 连接持续上传 PCM，同时接收 SSE 返回。Qwen 使用常驻模型的增长窗口解码；官方 vLLM 流式路径未接入，不需要安装 WSL。没有可靠句界时会保留上下文，裁窗可复用已安装的 Silero VAD；缺少可选资源时使用保守回退。

## 准备其他模型

一般在设置面板中选择模型并点击准备即可。也可以在项目环境中运行：

```powershell
.\.venv\Scripts\python.exe scripts/install_local_model.py --model kotoba-v2 --native-backend cuda
```

可用 ID：`kotoba-v2`、`qwen3-asr-0.6b`、`qwen3-asr-1.7b`、`voxtral-realtime`、`reazonspeech-k2`。

权重下载地址固定到发布者提交，按文件校验长度与 SHA-256。audio.cpp 运行时固定到 `v0.9.2-drama3-base-small`，保留上游文件和许可；ReazonSpeech 的可选依赖只安装到本项目 `.venv`。准备失败或取消时保留原设置，入口在关闭旧识别进程前检查新模型是否完整。
