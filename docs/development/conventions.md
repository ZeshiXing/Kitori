# 命名与目录规范

## 文件与符号

| 对象 | 规范 | 示例 |
| --- | --- | --- |
| Python 包/模块/测试 | ASCII、小写 `snake_case` | `continuous_capture.py`、`test_model_preferences.py` |
| Python 类 | `PascalCase`，以职责命名 | `ContinuousCapture`、`Preferences` |
| 函数/变量/配置字段 | `snake_case`，布尔字段表达状态 | `caption_idle_seconds`、`shadow_enabled` |
| 常量 | `UPPER_SNAKE_CASE` | `DEFAULT_WHISPER_BLOCKLIST` |
| PowerShell、C#、JSON | 小写 `snake_case`，保留上游固定名字 | `play_demo.ps1`、`windows_captions_reader.cs` |
| JavaScript/CSS | 文件小写 `snake_case`，JS 符号 `camelCase` | `layout.js`、`fitCaptionRows` |
| Markdown | 小写 `kebab-case` | `local-models.md` |
| Windows 用户入口 | `Start-<Output>.cmd`，单操作保留简单名 | `Start-Luna.cmd`、`Settings.cmd`、`Stop.cmd` |

保留惯例文件名 `README.md`、`CONTRIBUTING.md`、`THIRD_PARTY.md`、`AGENTS.md`、`LICENSE`、`pyproject.toml`、`requirements-lock.txt`。项目完整显示名为 **Kitori：日语实时字幕与振假名**（英文 **Kitori: Real-time Japanese Subtitles with Furigana**，日文 **Kitori：ふりがな付き日本語リアルタイム字幕**），发布文件使用 `Kitori-Setup.exe` 与 `Kitori-Source.zip`。现有 Python 分发标识 `japanese-caption-assistant`、导入名 `jcaption`、配置字段、Luna 注入标记和模型 ID 保持兼容，不随品牌名称调整。

主页译文使用 `README.en.md` 与 `README.ja.md`，根目录 `README.md` 为中文。文档截图放 `docs/images/`，使用小写 `kebab-case` 的功能描述名；素材署名集中在该目录的 `sources.md`，各语言主页在图片附近链接它。

单位写入名称：`*_seconds`、`*_ms`、`*_bytes`、`*_pid`。音频位置、媒体位置、单调时钟和墙上时间在接口/注释中明确。模型 ID、协议字段、现有配置名属于兼容接口，不能仅为美观改名。

## 按职责放置

- `jcaption/`：可导入核心，不放一次性机器实验。暂不为分目录而拆包，避免改变 Tiger 宿主导入边界。
- `scripts/`：被启动器/设置面板调用的运行、准备、安装入口，名称描述当前职责。
- `plugins/`：Tiger 官方接口插件；`japanese_caption.py` 为正常路径，其他入口用环境变量保护且正常启动不启用。
- `tools/diagnostics/`：人工选择的实机诊断，不能由自动测试发现后播放声音或切换用户模型。
- `tests/`：`test_<module_or_behavior>.py`，无需真实模型的回归测试。
- `docs/guides/`：当前用户说明；`docs/design/`：架构设计；`docs/development/`：开发约定。
- `config/`：只公开示例；真实配置、令牌、UI 偏好留本机。

生成文件进入已忽略的 `logs/`、`work/`。新日志名使用 `snake_case`；旧日志/状态名称涉及运行协议，不作无必要批量迁移。

## 改名规则

先查调用、导入、测试、文档和 PowerShell 进程匹配。移动后重新确认 `ROOT` 层级。进程匹配保留项目绝对路径约束，不得扩大到其他 Python 或 Luna。

