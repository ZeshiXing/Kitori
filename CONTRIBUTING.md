# 开发约定

先阅读 [README](README.md)、[目录与命名规范](docs/development/conventions.md)和[当前架构](docs/design/architecture.md)。使用项目自己的 `.venv`，不要向其他项目环境安装依赖。

## 修改范围

- `jcaption/` 放可复用业务逻辑，`scripts/` 做薄入口与运行环境协调。
- 使用上游推理、音频、VAD、分词库；方法参考和实际复用分别记入 `THIRD_PARTY.md`。
- 不修改 `apps/` 中签名的第三方分发文件。Tiger 使用支持的插件入口；Luna 只写用户配置扩展。
- 当前连续采集与识别调度作为稳定基线。目录、文档、设置界面维护不要顺便调整模型、VAD 或解码参数。
- 正常日志不能含音频、字幕正文、凭证；诊断必须显式启动并标明数据来源。观看音频不加入仓库。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

涉及识别适配时，另跑路由测试与真实 Tiger 宿主检查：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_runtime.py --mode local
```

真实播放与模型测试参见[诊断工具](tools/diagnostics/README.md)。不要把 mock、文字注入、合成声音或动画观察混报；说明模型、设备、场景、计时起点与局限。测试中开启的视频，结束时暂停并核验，不自动恢复播放。

设置修改需覆盖成功、失败、取消、重复操作与三语即时切换；新界面文本加入 `jcaption/ui_translations.json`，占位符保持一致。真实界面检查不能只依赖 mock。

## 提交

本项目自有代码使用 [GPL-3.0-only](LICENSE)。提交代码时确认有权以该许可贡献；保留引入代码原有的版权和许可声明，并在 `THIRD_PARTY.md` 记录实际复用。不要将网上可见但没有兼容授权的代码直接并入项目。

一次修改解决一个主题。标题使用具体动词，例如 `Fix download cancellation applying settings`；正文说明行为变化、验证与限制。不要提交本机配置、运行库、模型、日志、私人截图或密钥。首次公开发布使用[发布清单](docs/development/release.md)。
