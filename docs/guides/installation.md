# 安装与启动

## 图形安装器

双击 `Kitori-Setup.exe`，选择目录和识别方式后点击安装。安装器支持中、英、日三语，不需要预先安装 Python，也不需要管理员权限。它会将 Python、项目环境和下载的运行库放在所选目录，不修改系统 PATH 或其他 Python 环境。

- **Whisper turbo / NVIDIA**：准备 large-v3-turbo，使用 CUDA/float16，需要兼容的 NVIDIA 显卡和驱动。
- **Whisper small / CPU**：准备 small，使用 CPU/int8。之后可在设置里更换模型。
- **Windows 实时字幕**：跳过 Tiger 和本地模型下载，需要 Windows 11；先在 Windows 的字幕窗口启用功能、准备语言包并选择日语，再启动字幕。
- **Luna（可选）**：勾选后自动下载完整便携版；默认仍使用本项目的独立浮窗，可在设置中切换。

这是联网安装器。Whisper 首次下载约 5.1 GB Tiger 运行库与 0.5–1.6 GB 模型，加上 Python、依赖、解压文件与缓存，建议预留 20 GB。Windows 字幕方式建议预留 2 GB。下载均使用固定版本和校验值；大文件支持重新运行后续传。取消或失败后可选择原来的未完成安装目录重试。安装完成的目录不会被安装器覆盖。

当前安装器未做代码签名。安装完成后可创建桌面启动、设置和退出快捷方式。打开设置确认识别语言和显示端，再使用 `Start-Local.cmd` 启动。系统字幕第一次启用和语言包下载需要用户在 Windows 中完成。

## 从源码自动准备

源码根目录双击 `Install.cmd`，自动准备独立环境。默认检测到 `nvidia-smi.exe` 时选择 turbo/CUDA，否则选择 small/CPU。也可指定方式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/install.ps1 -Mode windows -Language ja
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/install.ps1 -Mode gpu -WithLuna
```

`-Mode` 可选 `gpu`、`cpu`、`windows`、`auto`；`-Language` 选择面板语言 `zh`、`en`、`ja`。已有本机配置不会被覆盖。脚本只对本次进程设置执行策略，不更改系统策略。

## 手动准备项目环境

Windows x64，Python 3.11+。锁定依赖使用 Python 3.13：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
Copy-Item config/caption.example.json config/caption.json
```

复制配置仅供首次使用，已有文件不要覆盖。其他 Python 版本可用 `pip install -e .` 解析依赖范围。Qt WebEngine 用于原生窗口内部排版，正常使用无需浏览器。

| 资源 | 项目预期位置 | 固定版本 |
| --- | --- | --- |
| Tiger Windows 便携包 | `apps/TigerBackend/audioWhisper/audioWhisper.exe` | v1.3.20.1 |
| Luna（可选） | `apps/LunaTranslator/LunaTranslator_x64/LunaTranslator.exe` | v12.1.2.11 |
| FFmpeg / FFprobe | PATH 或配置 `ffmpeg_bin` 指向 bin 目录 | Tiger 包内提供 |

这些是安装器使用的路径，通常不需要手动整理。准备好 Python 环境后，仍建议运行 `Install.cmd`，让它一并准备 Tiger、语音分段所需的 Silero 文件和 Whisper 模型。只拷贝 Tiger 主程序或模型权重并不足以运行连续识别。Windows 来源无需这些资源，使用系统自带的 .NET Framework C# 编译器准备只读 UIA 桥接。

如果最初选择了 Windows 字幕，后来想换成本地模型，可以在安装目录运行 `Install.cmd` 准备本地运行库，然后到设置里切换识别来源。已有设置会保留。

打开 `Settings.cmd` 选择来源、语言、显示端和模型，按提示准备并应用。Whisper 也可手动下载：

```powershell
.\.venv\Scripts\python.exe scripts/fetch_model.py --model large-v3-turbo
```

手动复制的示例配置使用 CUDA/float16。无兼容 NVIDIA GPU 时，先在 `config/caption.json` 调整 `device` / `compute_type`，例如 `cpu` / `int8`。当前面板没有统一 Whisper 设备控件。[其他模型与设备](local-models.md)

## 卸载与 Luna 扩展

先退出字幕程序。安装器不写入全局 Python 或系统 PATH；项目环境和运行库都在安装目录，桌面快捷方式可单独移除。如果要保留模型或设置，可先备份对应目录。

移除 Luna 扩展前关闭该便携 Luna，再运行：

```powershell
.\.venv\Scripts\python.exe scripts/configure_luna.py --disable
```

只移除本项目额外 HTML 标记段，恢复接管前的相关设置；标记外 HTML 和用户后来改过的相关选项保留，不操作其他路径的 Luna。

## 构建安装器

安装器使用 Windows 自带的 .NET Framework C# 编译器。构建前准备本项目 Python 环境；从 Git 仓库或公开源码 ZIP 均可构建：

```powershell
.\.venv\Scripts\python.exe scripts/build_installer.py
```

输出 `dist/Kitori-Setup.exe`。EXE 内含公开项目源码、安装脚本和许可通知，不嵌入第三方运行库、模型或个人配置。`scripts/build_installer.py` 同时遵循 Git 忽略规则和固定排除列表，实验记录、日志及本机配置不会进入安装器。发布时将安装器与对应源码一起提供。
