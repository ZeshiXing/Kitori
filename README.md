# Kitori：日语实时字幕与振假名

[简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md)

Kitori（キトリ）的名字取自日语「聞き取り」（kikitori，听辨、听懂）。

一个 Windows 桌面字幕工具，主要给想通过日语视频、动画学习日语的人用。

播放视频时，它会把听到的日语显示在悬浮窗里，并在汉字上方标出振假名（ふりがな）。听不清的地方可以对照原文，遇到不熟悉的汉字也能看看读音。如果平时用 LunaTranslator，还可以把字幕送到 Luna，接着用它的查词和翻译功能。

它采集的是电脑正在播放的声音，不绑定某个网站或播放器，所以会议、网课、直播等场景也能用。识别语言可以在设置中选择，具体支持哪些语言取决于所用模型。

目前还在开发中（Alpha），提供 Windows 联网安装器，也可以从源码运行。

![全屏日语视频与实时原文、振假名字幕](docs/images/fullscreen-furigana.png)

*下方半透明窗口是程序生成的字幕，白色是已经确认的部分，浅蓝色是还在识别的部分。视频里的大字是素材自带的。视频：Akaniji，CC BY 4.0；地图：つる１２１４，CC BY-SA 3.0。[素材署名与截图说明](docs/images/sources.md)*

## 功能

重点是看视频时字幕能跟得上，不用等一整段话说完才出现。识别中的文字会先显示出来，再随着后续语音修正；注音也会跟着更新，尽量减少文字来回跳动。

- 日语原文和振假名一起显示，已确认与识别中的文字用不同颜色区分。
- 字幕默认居中，正文最多两行，一段时间没有新文字就清空。
- 字体、描边、阴影、背景透明度和字幕保留时间都可以调整。
- 自带桌面悬浮窗，不需要打开网页；也可以选 Luna 显示，或同时开两个窗口。
- 播放可读取的本地媒体时，可以开启音频预读；预读用不了就继续实时识别。

音频采集、语音模型和分词使用已有的开源组件。这个项目主要处理字幕何时更新、哪些文字先保留，以及注音怎么跟着文字变化。[用到的项目和参考方法](THIRD_PARTY.md)

## 可选 Luna 显示

![同一日语视频上的 Luna 字幕与点词查词窗口](docs/images/fullscreen-luna.png)

*图中是 Luna 的点词查词窗口，需要先在 Luna 配好词典；这里显示的词条来自 JapanDict / JMdict。两张截图用的是同一段开放许可日语新闻视频，朗读为合成语音，只用于展示界面。[素材与词典署名](docs/images/sources.md)*

## 识别与显示选项

| 项目 | 当前支持 |
| --- | --- |
| 本地模型 | Whisper、Kotoba-Whisper v2、Qwen3-ASR、Voxtral Mini 4B Realtime、ReazonSpeech K2 v2 |
| 系统字幕来源 | Windows Live Captions，需先在 Windows 中启用并准备识别语言 |
| 显示端 | 独立悬浮窗、LunaTranslator、两者同时 |
| 设置面板 | 中文、日本語、English；界面语言与识别语言分别设置 |
| 日语辅助 | Sudachi 注音；Whisper/Kotoba 可选幻觉词汇屏蔽 |
| 本地媒体预读 | 当前适用于 Whisper/Kotoba；其他后端继续实时识别 |

识别使用本地模型或 Windows Live Captions，不需要云端 STT API 密钥。程序本身显示语音原文；需要翻译的话，可以另行配置 Luna。[模型与设备说明](docs/guides/local-models.md)

## 安装与启动

双击 [Kitori-Setup.exe](https://github.com/ZeshiXing/Kitori/releases/download/v0.3.0/Kitori-Setup.exe)，选择安装目录和识别方式，点击安装即可。安装器会准备独立的 Python 环境、依赖和所选识别运行库；不需要先装 Python，也不需要管理员权限。

| 安装方式 | 适用情况 |
| --- | --- |
| Whisper turbo / NVIDIA | 使用兼容 NVIDIA 显卡运行 large-v3-turbo |
| Whisper small / CPU | 没有兼容显卡时使用 small 模型；速度取决于 CPU |
| Windows 实时字幕 | 使用系统字幕，需要 Windows 11 并手动启用所需语言包 |

这是联网安装器。Whisper 首次需要下载约 5.1 GB 的 Tiger 运行库和 0.5–1.6 GB 模型，建议预留 20 GB 空间；Windows 实时字幕方式跳过这些下载。Luna 可在安装时勾选。下载失败可以重新运行安装器继续。

完成后打开设置，选择识别语言和显示端。默认是日语和独立悬浮窗，之后也能更换模型。[详细安装说明](docs/guides/installation.md)

| 入口 | 用途 |
| --- | --- |
| `Start-Local.cmd` | 启动独立字幕浮窗 |
| `Start-Luna.cmd` | 使用已安装的 Luna 显示字幕 |
| `Start-Both.cmd` | 同时显示两者 |
| `Settings.cmd` | 打开设置 |
| `Stop.cmd` | 退出字幕程序 |

采集的是默认输出设备，切换耳机/扬声器后需重启。关闭设置窗口不会退出字幕程序。[设置操作说明](docs/guides/settings.md)

### 从源码安装

下载源码后也可以双击 `Install.cmd`，自动准备环境；默认根据是否找到 NVIDIA 工具选择 Whisper turbo 或 CPU small。手动安装步骤见安装说明。源码环境要求 Windows x64、Python 3.11+，锁定依赖使用 Python 3.13。

## 使用时要注意

短句、背景音乐、多人同时说话和人名地名都可能识别错，注音也不一定正确。用来学日语时，遇到不通顺的地方最好再听一遍或查一下。字幕速度和准确性也会受模型、电脑配置和音源影响。

Whisper、Kotoba、Qwen 和 Reazon 目前通过反复识别一段滚动音频来更新字幕，Voxtral 则使用它的实时接口。因此，“每隔多久更新一次”不等于实际听到声音后多久能看到字幕。

桌面采集只能听到已经播放的声音。预读目前限于 Whisper/Kotoba 和可读取的本地媒体，不支持受 DRM 保护的网站，也还没有接入 Edge 网页播放器的持续时钟同步。

Luna 接入不改它的 EXE、DLL 或源码，不过注音扩展用到了与版本有关的渲染接口，更新 Luna 后可能需要重新检查。

## 隐私与开发

正常使用时，采集的音频不保存到磁盘，默认日志也不记录识别文字；最近字幕只在内存中保留有限条数。本地服务只监听 `127.0.0.1`，发送字幕的接口有每次启动生成的令牌。下载模型和运行库需要联网；如果使用 Luna 的在线词典或翻译，它们会按各自设置访问网络。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

自动化测试与真实模型、桌面音频、界面绘制验证分开进行。[贡献与命名规范](CONTRIBUTING.md) · [真实运行诊断](tools/diagnostics/README.md) · [发布检查](docs/development/release.md)

## 许可与致谢

本项目自有代码按 **GPL-3.0-only** 发布，详见 [LICENSE](LICENSE)。第三方代码、模型、字典、运行库和演示素材保留各自许可；项目自有截图贡献使用 **CC BY-SA 4.0**；图中第三方界面、插画与商标有单独的权利例外，见素材说明。

感谢 Whispering Tiger、faster-whisper、LunaTranslator、Sudachi、Silero VAD，以及流式识别相关开源项目提供的组件和方法参考。[第三方说明](THIRD_PARTY.md) · [演示素材与截图署名](docs/images/sources.md) · [分发说明](docs/development/licensing.md)
