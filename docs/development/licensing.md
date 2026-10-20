# 许可与分发

项目自有代码使用 **GPL-3.0-only**，即 GNU GPL 第 3 版，不自动授权将来版本。全文见 [LICENSE](../../LICENSE)，Python 元数据使用同一 SPDX 标识。版权仍归各自作者所有。

## GPL 覆盖什么

除另有明确声明外，项目自有代码按 GPL-3.0-only 提供。第三方代码、字体、模型、字典、便携程序和运行库保留各自许可证，不能因为项目选 GPL 就删除它们的声明。来源及参考方法记录在 [THIRD_PARTY.md](../../THIRD_PARTY.md)。

GPL 允许商业使用、收费分发、私人使用和修改。分发受 GPL 覆盖的修改作品时，应保留许可证/版权通知，说明修改，并按 GPL 提供对应源码。仅自己修改使用，一般不因此必须公开；GPL 也不是“禁止商用”或“所有连接程序自动开源”的许可证。具体义务以许可证正文及实际组合/分发方式为准。

## 第三方许可

- Luna 使用 GPLv3；本项目现在的许可方向与 GPLv3 代码复用相容。若以后实际复制代码，应保留上游版权/许可证和修改说明，不能只写“参考”。当前来源清单仍描述实际实现，不因改许可证而虚构复用。
- Tiger、faster-whisper、QtAwesome 等采用 MIT；引入其代码/副本时仍须保留原许可和版权声明。
- SudachiPy、Requests、audio.cpp 等采用 Apache-2.0；Apache 官方说明其可纳入 GPLv3 作品，适用的许可证、NOTICE 与修改说明仍须保留。
- PySide6 6.12.0 元数据声明可选择 LGPLv3/GPLv2/GPLv3；Qt WebEngine/Chromium 与其他子组件另有通知，不能用这一行元数据代替全部检查。
- Sudachi 字典、模型与推理依赖按具体发布版本和内容分别核对；当前不随项目源码分发。Windows Live Captions 和语言包由用户 Windows 提供，不重新分发。

## 当前源码发布范围

只分发项目源码、启动脚本、文档、前端文件与配置示例。排除 `apps/`、`.venv/`、`models/`、`downloads/`、`logs/`、`work/`、真实用户配置和观看内容。模型目录中的公开 URL/校验值不代表随源码附带权重。

主页文档另附两张开放许可日语视频的截图，完整署名见 [截图素材说明](../images/sources.md)。项目自有截图贡献使用 CC BY-SA 4.0；第三方视频、地图、词典数据按原许可保留通知，Luna/JapanDict 的界面、插画与商标不在本项目授权范围内。截图许可不改变程序的 GPL-3.0-only，也不构成对第三方 UI 的重新授权。完整视频不随源码分发。

联网安装器只嵌入项目公开源码与通知，uv、Python、Tiger、可选 Luna、模型和 Python 依赖在用户安装时从固定来源准备，保留下载分发中的许可文件。编译的安装器与匹配项目源码一同提供。若以后改成离线整合包，需按实际包含文件补齐第三方许可、对应源码提供方式和必要安装信息，保留签名与安全机制。仅附上本项目 LICENSE 不足以覆盖所有外部组件。

GPL 只处理软件许可，不授予动画内容、服务商标、受保护媒体访问或绕过 DRM 的权利。当前项目不分发动画内容，也不实现 DRM 绕过；网站使用仍应符合实际服务条款与适用规则。

## 参考

- [GPL-3.0-only 正文（SPDX）](https://spdx.org/licenses/GPL-3.0-only.html)
- [GNU GPLv3 摘要与全文](https://choosealicense.com/licenses/gpl-3.0/)
- [Apache 官方 GPL 兼容说明](https://www.apache.org/licenses/GPL-compatibility.html)
- [Luna LICENSE](https://github.com/HIllya51/LunaTranslator/blob/main/LICENSE)
- [Tiger LICENSE](https://github.com/Sharrnah/whispering/blob/main/LICENSE)
- [Qt for Python 第三方许可说明](https://doc.qt.io/qtforpython-6/licenses.html)
