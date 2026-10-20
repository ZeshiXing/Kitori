# 当前架构

```text
scripts/launch.ps1
  → 配置/资源检查 → 停止本项目旧进程 → prepare_runtime → run_backend
  → Tiger 官方插件宿主 / Windows UIA 桥接
  → 本地字幕服务（127.0.0.1，进程间令牌）
  → 独立原生浮窗 / Luna 用户额外 HTML
```

## 采集与识别

`plugins/japanese_caption.py` 在 Tiger 官方宿主中启动 `ContinuousCapture`，复用 PyAudioWPatch、宿主重采样和官方 Silero VADIterator，保留起止之间全部音频。有限队列合并同句过时草稿、保留完成短句；单一识别线程复用常驻模型。旧 Tiger 捕获路径为内部配置回退。

`local_asr.py` 适配上游推理。Whisper/Kotoba 等离线后端由 `rolling_asr.py` 复用相同输入、封存有可靠停顿的旧段、重复解码尾窗；Voxtral 使用持久 PCM 会话，不宣称所有模型都有原生编码器/KV 缓存。

Windows 只读 UIA 桥接读取系统字幕，`windows_captions.py` 协调滚动窗口与停顿确认，跳过模型/预读。本项目 final 不冒充系统模型的最终信号。

## 字幕与显示

`state.py` 管理会话、句子、修订、草稿/确认状态并过滤迟到结果。`annotation.py` 复用 Sudachi 与有界缓存，注音只应用于仍匹配的正文。`server.py` 通过 SSE 更新显示端。

`overlay.py` 的 Qt 窗口嵌入项目 ruby 页面，`web/layout.js` 处理正文行数。`luna.py` / `web/luna.js` 使用额外 HTML 和已加载渲染接口，完成句进入官方文本输入接口；Luna 不参与采集或 ASR，独立浮窗不依赖 Luna。

`lookahead.py` 管理可读取本地媒体的有限任务、时钟和缓存，缓存缺口/时钟失联立即回到实时路径。没有受保护网站音频提取或 Edge 持续时钟连接。

## 设置与进程

`preferences.py` 是三语 Qt 表单。识别选择暂存，准备成功后由 `settings.py` 原子保存，`lifecycle.py` 请求重启。外观/面板语言即时写本机 `overlay.json` / `ui.json`。关闭表单不终止字幕；退出由 `stop.ps1` 按精确项目路径清理，包括 venv 子进程，避免操作其他项目。

`run_backend.py` 拥有服务和识别宿主，按显示端启动浮窗或 `session_tray.py`。日常日志只写状态/计数，不落盘观看音频与正文。运行库、模型、日志和真实配置排除在源码包外。
