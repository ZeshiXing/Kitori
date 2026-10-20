# 真实环境诊断

需要人工选择场景。部分工具播放合成声音、占用字幕端口、切换模型或启动 GPU 推理，不属于自动测试。先读源码/参数，保持其他视频暂停，避免同时占用同一端口/模型；不要在用户观看时自动执行。

从根目录用 `.venv\Scripts\python.exe tools/diagnostics/<name>.py`：

| 工具 | 场景与前提 |
| --- | --- |
| `verify_streaming.py` | 合成日语→扬声器回环→当前后端→字幕；需启动识别与 Haruka 声音 |
| `verify_luna_output.py` | 文字注入/Luna 绘制；停止正常字幕服务、保留 Luna |
| `check_caption_layout.py` | Qt WebEngine 合成文字排版，无模型 |
| `check_luna_clearing.py` / `check_live_caption_display.py` | Luna 清理/行数/空闲清空，需便携 Luna |
| `verify_local_models.py` / `verify_rolling_asr.py` | 显式选模型的合成 PCM 检查，需模型与运行库 |
| `verify_onset.py` | 回环/句首时序，可能播放合成音频 |
| `play_demo.ps1` | 生成或播放自编合成日语，供回环诊断使用 |
| `observe_anime_model.py` | 人工同步标记后的动画观察，会按参数切换模型 |
| `check_short_anime.py` | 四分钟人工同步诊断；原始音频/正文仅在内存，参考推理前需暂停并释放主模型 |

移动后确认 `ROOT` 解析层级。Tiger 诊断插件用显式环境变量启用，正常启动不执行。音频/准确率与纯显示验证分别报告，报告留在已忽略目录。
