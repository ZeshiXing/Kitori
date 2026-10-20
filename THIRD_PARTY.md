# Method references and dependencies

## Project license and distribution scope

The project's own code is licensed under **GPL-3.0-only**, unless a file
explicitly states otherwise; see [LICENSE](LICENSE). Copyright remains with
the respective authors. This grant does not replace upstream copyright,
license or attribution notices and does not relicense external assets.

The current source distribution excludes all portable applications, model
weights, dictionaries, Python environments and private captured media. The
credited documentation screenshots are included separately. A dependency
being downloadable or installed locally is not permission to redistribute it
under the project's license. Any future binary bundle needs a component-level
license/source/notice check, including Qt WebEngine/Chromium, icon fonts,
FFmpeg, Tiger's bundled dependencies and dictionary source notices.

The installed PySide6 6.12.0 package metadata declares
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; this is not a statement that
every Qt module, Chromium component or bundled font has the same license.
Apache-2.0 code may be included in a GPLv3 work subject to retaining its
applicable license and notices; see the
[Apache Software Foundation's compatibility guidance](https://www.apache.org/licenses/GPL-compatibility.html).
See also [project licensing notes](docs/development/licensing.md).

## Documentation media

The README screenshots contain separately licensed demonstration media and,
in the optional Luna image, third-party dictionary UI. See
[screenshot sources and license exceptions](docs/images/sources.md) for full
credits. Screenshot contributions use CC BY-SA 4.0; this does not relicense
the depicted third-party site UI, illustrations or marks. The GPL code
license does not replace any of those rights. The full demo video is not
included in the source distribution.

## Online installer

The independent WinForms bootstrapper is built from `scripts/setup.cs` and
embeds the public project sources and notices. It uses Windows' .NET Framework
and downloads external runtimes at installation time rather than embedding
them in the EXE.

- [uv](https://github.com/astral-sh/uv), version 0.13.3, Apache-2.0 OR MIT:
  the pinned Windows archive prepares an isolated Python installation and
  project environment. Its upstream license files are retained. See
  [uv's Python distributions documentation](https://docs.astral.sh/uv/concepts/python/versions/)
  for the [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
  distributions it manages. CPython and bundled libraries retain their own
  notices in the downloaded runtime. No system Python, PATH or registry entry
  is modified by this installer.
- Tiger v1.3.20.1 and optional Luna v12.1.2.11 are downloaded as their complete
  upstream portable distributions, preserving program files and notices.
  Tiger's bundled FFmpeg remains in its original `toolchain/ffmpeg` directory.
  Silero VAD is prepared from its official source archive, pinned to commit
  `1e261b036686cd0017d500ee96acd1c4ba572a9d`; both the archive and used JIT/utility
  files have pinned SHA-256 values. The complete MIT-licensed source/model
  archive and notices remain in the external cache. Only the archive's top
  directory is renamed to match the existing cache path; inference files are
  unchanged.
  Model archives and external runtime archives are checked with pinned SHA-256
  values; Python dependencies are installed from the public package index.

Installer sources are part of this GPL-3.0-only project. Distribute the matching
public source alongside a compiled installer; do not turn a downloaded external
runtime into a project-owned GPL asset by bundling it without its own notices.

## Methods and components

The project's own code handles versioned caption state, stability at Japanese
word boundaries, asynchronous reading updates, stale-result rejection and a
local caption view. It does not implement an ASR model, an audio codec or a
Japanese morphological analyzer.

- [Whisper-Streaming](https://github.com/ufal/whisper_streaming), MIT: method
  reference for LocalAgreement's agreement between successive hypotheses.
  The display state in `jcaption/state.py` and timestamp/agreement trimming in
  `jcaption/rolling_asr.py` are independently written for this project. The
  upstream audio-processing implementation is not copied; word alignment is
  supplied by faster-whisper.
- [SimulStreaming](https://github.com/ufal/SimulStreaming), MIT: comparison
  candidate and design reference. AlignAtt is not implemented by this project.
- [WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit), Apache-2.0:
  reference for temporary/committed transcript separation and streaming sessions.
  It is not a runtime dependency of the current implementation.
- [Whispering Tiger](https://github.com/Sharrnah/whispering), MIT: current
  capture/VAD/queue and model-host adapter. The portable distribution and its
  licenses remain under the ignored `apps/` directory. Plugins are installed
  through its supported plugin interface; upstream source files are unmodified.
  `jcaption/model_catalog.json` records public model download URLs and SHA-256
  values from Tiger v1.3.20.1's `Models/STT/faster_whisper.py`; no inference or
  download implementation was copied for the settings UI.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper), MIT: model inference
  through Tiger's bundled runtime. Whisper model weights are external assets.
- [Kotoba-Whisper v2.0](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0),
  Apache-2.0 model; its publisher's CTranslate2 conversion is
  [kotoba-whisper-v2.0-faster](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0-faster)
  (conversion card declares MIT). Both source notices must be retained for redistribution.
- [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR), Apache-2.0, and
  [Voxtral Mini 4B Realtime](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602),
  Apache-2.0: external model weights. The pinned Q8/Q4 GGUF files are published
  by [audio-cpp](https://huggingface.co/audio-cpp/audio.cpp-gguf).
- [audio.cpp](https://github.com/0xShug0/audio.cpp), Apache-2.0, pinned release
  `v0.9.2-drama3-base-small`: external persistent native inference server.
  The independent adapter uses its documented multipart and full-duplex live PCM
  interfaces; no inference implementation is copied. Runtime archives retain
  their original libraries and notices under ignored `apps/audio.cpp/`.
  Tiger's `Models/audio_cpp_runtime.py` and `Models/STT/audio_cpp.py` were read
  as orchestration references; our downloader/client are independently written.
- [ReazonSpeech K2 v2](https://huggingface.co/reazon-research/reazonspeech-k2-v2),
  Apache-2.0: external Japanese INT8 ONNX weights, run by
  [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 1.13.3 (Apache-2.0)
  in a project-owned persistent Python worker. NumPy is BSD-3-Clause.
  `jcaption/local_model_catalog.json` records immutable publisher revisions,
  exact file sizes, and SHA-256 values. These weights and runtimes are excluded
  from the source package; the installer verifies them before marking them ready.
- [SudachiPy / sudachi.rs](https://github.com/WorksApplications/sudachi.rs),
  Apache-2.0: installed Japanese tokenizer and reading provider, version 0.6.11.
- [SudachiDict](https://github.com/WorksApplications/SudachiDict): external
  dictionary package, small edition 20260723. Preserve its bundled licensing
  and source notices when redistributing the dictionary.
- [Requests](https://github.com/psf/requests), Apache-2.0: local caption service
  and Luna HTTP display adapter. Transitive package notices remain in `.venv`.
- [LunaTranslator](https://github.com/HIllya51/LunaTranslator), GPL-3.0: optional
  external display process invoked through its text-input HTTP interface. The
  optional user extra-HTML adapter also calls its already-loaded WebView renderer
  for incremental ruby text and native dictionary interactions. No renderer source
  is copied; the private function contract is version-sensitive. Only user
  configuration/extra HTML is installed, never patches to program files. Its
  distribution is separate from this source package. The independent caption
  page and Sudachi reading provider do not require Luna.

Python's standard library supplies the local HTTP server; the browser's native
HTML `ruby`/`rt` elements supply annotation layout. No model weights, upstream
portable distributions, runtime environment, user key files or capture logs are
included in the source repository.

The desktop window uses [Qt for Python / PySide6](https://doc.qt.io/qtforpython/),
6.12.0, including Qt WebEngine and Qt Multimedia; retain their distributed
license and third-party notices. Its frameless-window and embedded-rendering
design was informed by Luna's `gui/translatorUI.py`, `gui/buttonbar.py`,
`gui/setting/display_ui.py`, `gui/textbrowser.py` and `gui/rendertext/webview.py`.
The frameless overlay follows its toolbar visibility, icon colors and separate
toolbar/text background pattern. Those GPL source files were read as references,
not copied into this implementation. The Qt wrapper and local media controls
are independently written; existing project ruby rendering is reused.

Toolbar icons use [QtAwesome](https://github.com/spyder-ide/qtawesome) 1.4.2
(MIT), QtPy 2.4.3 (MIT), and its packaged Font Awesome font assets; preserve
the packages' font and license notices. No Luna source or binary assets were
copied into this project's source package.
# Windows 实时字幕方法参考

- [SakiRinn/LiveCaptions-Translator](https://github.com/SakiRinn/LiveCaptions-Translator)，参考提交 `a6fee12757b15edbeef7c60f8895e0be694801e1`，Apache-2.0：参考其通过 Windows UI Automation 读取 `CaptionsTextBlock` 的方法。未复制其 C# 实现、翻译器或界面代码。项目的只读桥接、滚动文本协调、字幕版本事件及注音显示独立实现。Windows Live Captions 及识别语言包由用户的 Windows 提供，不随本项目分发。


- [Silero VAD](https://github.com/snakers4/silero-vad), MIT: existing official JIT/ONNX models and public segmentation utilities from Tiger’s installed cache identify speech pauses. `jcaption/speech_boundary.py` calls the unmodified utilities or sherpa-onnx; it does not copy VAD inference. Its boundaries only split audio, never remove samples. If optional resources are missing, the scheduler retains its conservative fallback. Original notices remain with the external runtime.

Tiger onset protection uses its existing recording callback registry, with method reference commit `9750c19a1eb4dde8309af6ee74888b28d0e27907`. The independent bounded ring/timing implementation is `jcaption/capture_onset.py`; no upstream recording source is copied or patched. Registry availability and source-format preroll were verified in the installed portable runtime.

The default continuous pipeline runs inside Tiger's official plugin host, calling existing PyAudioWPatch, `audio_tools.resample_audio`, loudness normalization and the installed official Silero `VADIterator` directly. `jcaption/continuous_capture.py` implements only continuous buffering and bounded draft/final scheduling. The original callback guard remains for the optional legacy capture path; no upstream VAD, codec or resampling implementation is copied into project source.
