"""Native preferences for local recognition and Luna-style display."""
import json
from pathlib import Path
import sys
import time
import os
import subprocess

from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
                               QComboBox, QDoubleSpinBox, QSpinBox, QTabWidget,
                               QWidget, QPushButton, QProgressBar, QSlider,
                               QCheckBox, QColorDialog, QFontComboBox, QScrollArea, QFrame,
                               QPlainTextEdit)
from .settings import MODELS, LANGUAGES, model_installed, read_json
from .local_models import (EXTRA_MODELS, backend_for, is_whisper, model_label, model_ready,
                           validate_language)
from .i18n import translate, load_ui_language, save_ui_language, install_qt_language
from .lifecycle import request_exit
from .whisper_filter import DEFAULT_WHISPER_BLOCKLIST, validate_blocklist


class Preferences(QDialog):
    def __init__(self, root, config, appearance, appearance_changed, apply):
        super().__init__()
        self.root, self.config, self.appearance = Path(root), config, appearance
        self.appearance_changed, self.apply = appearance_changed, apply
        self.ui_language = load_ui_language(root)
        install_qt_language(self.ui_language)
        self.download = None
        self.restart = None
        self.download_message = None
        self.download_cancelled = False
        self.setWindowTitle('Kitori — ' + self.tr('字幕设置'))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        language_row = QHBoxLayout()
        self.ui_language_label = QLabel(self.tr('面板语言'))
        language_row.addWidget(self.ui_language_label)
        self.interface_language = QComboBox()
        for label, code in [('中文', 'zh'), ('日本語', 'ja'), ('English', 'en')]:
            self.interface_language.addItem(label, code)
        self.interface_language.setAccessibleName(self.tr('面板语言'))
        self.interface_language.setCurrentIndex(self.interface_language.findData(self.ui_language))
        language_row.addWidget(self.interface_language)
        language_row.addStretch()
        layout.addLayout(language_row)
        layout.addWidget(self.tabs)
        self.style_notice = QLabel(self.tr('显示与文字设置即时预览并自动保存。'))
        if config.get('display_mode') == 'luna':
            self.style_notice.setText(self.tr('Luna 的字体、阴影和背景在 Luna 中调整；双色颜色会实时同步。\n'
                                      '上一句保留、正文行数和空闲清空用于两种显示端；其余样式用于独立字幕浮窗。'))
        self.style_notice.setWordWrap(True)
        self.style_notice.hide()
        layout.addWidget(self.style_notice)
        recognition = QFormLayout()
        self.runtime = QLabel(self.tr('正在读取识别状态…'))
        self.runtime.setWordWrap(True)
        recognition.addRow(self.runtime)
        self.output = QComboBox()
        for label, value in [(self.tr('独立字幕浮窗'), 'overlay'), (self.tr('Luna 字幕框'), 'luna'), (self.tr('两者同时显示'), 'both')]:
            self.output.addItem(label, value)
        self.output.setAccessibleName(self.tr('字幕显示端'))
        self.output.setCurrentIndex(max(0, self.output.findData(config.get('display_mode', 'overlay'))))
        recognition.addRow(self.tr('字幕显示端'), self.output)
        self.source = QComboBox()
        self.source.addItem(self.tr('本地模型'), 'models')
        self.source.addItem(self.tr('Windows Live Captions · 系统实时字幕'), 'windows_livecaptions')
        self.source.setAccessibleName(self.tr('识别来源'))
        self.source.setCurrentIndex(max(0, self.source.findData(config.get('recognition_source', 'models'))))
        recognition.addRow(self.tr('识别来源'), self.source)
        self.windows_note = QLabel(self.tr('Windows 来源不加载本地模型。识别语言请在系统实时字幕中设置；下方语言用于注音。\n'
                                  '首次使用需要下载语言包；完成后可最小化系统字幕窗口。'))
        self.windows_note.setWordWrap(True)
        recognition.addRow(self.windows_note)
        self.windows_settings = QPushButton(self.tr('打开 Windows 实时字幕设置窗口'))
        self.windows_settings.clicked.connect(self.open_windows_captions)
        recognition.addRow(self.windows_settings)
        self.language = QComboBox()
        for code, label in LANGUAGES.items():
            self.language.addItem(self.tr(label) + (f' ({code})' if code != 'auto' else ''), code)
        self.language.setAccessibleName(self.tr('STT 识别语言'))
        self.language.setCurrentIndex(max(0, self.language.findData(config.get('language', 'auto'))))
        self.language_label = QLabel(self.tr('识别语言'))
        recognition.addRow(self.language_label, self.language)
        self.model = QComboBox()
        for name in MODELS:
            suffix = (self.tr('已就绪') if model_ready(root, name, config.get('local_native_backend', 'vulkan')) else
                      self.tr('需准备运行环境') if model_installed(root, name) else self.tr('需下载'))
            self.model.addItem(f'{model_label(name)} · {suffix}', name)
        self.model.setAccessibleName(self.tr('本地 STT 模型'))
        self.model.setCurrentIndex(max(0, self.model.findData(config.get('local_model', 'large-v3-turbo'))))
        recognition.addRow(self.tr('本地模型'), self.model)
        self.whisper_quality = QComboBox()
        for label, value in [(self.tr('快速 · 1 个候选'),1),(self.tr('平衡 · 3 个候选'),3),(self.tr('高 · 5 个候选，计算更慢'),5)]:
            self.whisper_quality.addItem(label,value)
        self.whisper_quality.setAccessibleName(self.tr('Whisper 草稿识别精度'))
        self.whisper_quality.setCurrentIndex(max(0,self.whisper_quality.findData(config.get('whisper_draft_beam',1))))
        self.whisper_quality_label = QLabel(self.tr('Whisper 草稿精度'))
        recognition.addRow(self.whisper_quality_label,self.whisper_quality)
        self.whisper_standard = QCheckBox(self.tr('采用 Whisper 标准温度回退和段内上下文（可能增加耗时）'))
        self.whisper_standard.setChecked(config.get('whisper_standard_decode',False) is True)
        self.whisper_standard.setAccessibleName(self.tr('Whisper 标准解码'))
        recognition.addRow(self.whisper_standard)
        self.native_backend = QComboBox()
        for label, value in [(self.tr('Vulkan · 兼容 GPU，速度可能不足'), 'vulkan'),
                             (self.tr('CUDA 13.3 · NVIDIA 推荐，需兼容驱动'), 'cuda'), ('CPU', 'cpu')]:
            self.native_backend.addItem(label, value)
        self.native_backend.setAccessibleName(self.tr('Qwen 和 Voxtral 推理设备'))
        self.native_backend.setCurrentIndex(max(0, self.native_backend.findData(config.get('local_native_backend', 'vulkan'))))
        self.native_label = QLabel(self.tr('Qwen / Voxtral 设备'))
        recognition.addRow(self.native_label, self.native_backend)
        self.native_device = QSpinBox()
        self.native_device.setRange(-1, 15)
        self.native_device.setSpecialValueText(self.tr('自动优先独立显卡'))
        self.native_device.setValue(config.get('local_native_device', -1))
        self.native_device.setAccessibleName(self.tr('Qwen 和 Voxtral 设备编号'))
        self.native_device_label = QLabel(self.tr('设备编号'))
        recognition.addRow(self.native_device_label, self.native_device)
        self.chunk_seconds = QDoubleSpinBox()
        self.chunk_seconds.setRange(.25, 2)
        self.chunk_seconds.setSingleStep(.25)
        self.chunk_seconds.setSuffix(self.tr(' 秒'))
        self.chunk_seconds.setValue(config.get('local_stream_chunk_seconds', .5))
        self.chunk_seconds.setAccessibleName(self.tr('本地流式更新间隔'))
        recognition.addRow(self.tr('音频更新间隔'), self.chunk_seconds)
        self.model_note = QLabel()
        self.model_note.setWordWrap(True)
        recognition.addRow(self.model_note)
        self.whisper_filter = QCheckBox(self.tr('屏蔽幻觉词汇'))
        self.whisper_filter.setAccessibleName(self.tr('Whisper 屏蔽幻觉词汇'))
        self.whisper_filter.setChecked(config.get('whisper_blocklist_enabled', False) is True)
        self.whisper_phrases = list(config.get('whisper_blocklist', DEFAULT_WHISPER_BLOCKLIST))
        self.whisper_filter_edit = QPushButton(self.tr('编辑屏蔽词表…'))
        self.whisper_filter_edit.clicked.connect(self.edit_whisper_blocklist)
        filter_row = QHBoxLayout()
        filter_row.addWidget(self.whisper_filter)
        filter_row.addWidget(self.whisper_filter_edit)
        self.whisper_filter_row = QWidget()
        self.whisper_filter_row.setLayout(filter_row)
        recognition.addRow(self.whisper_filter_row)
        note = QLabel(self.tr('Default 自动判断语言；日语专用模型按日语识别。\n'
                      '模型和识别语言设置在“应用并重启”后生效。'))
        note.setWordWrap(True)
        recognition.addRow(note)
        self.add_tab(recognition, self.tr('识别与语言'), scroll=True)

        display = QFormLayout()
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setAccessibleName(self.tr('字幕背景不透明度'))
        self.opacity_text = QLabel()
        row = QHBoxLayout()
        row.addWidget(self.opacity)
        row.addWidget(self.opacity_text)
        display.addRow(self.tr('背景不透明度'), row)
        self.color_buttons = {}
        display.addRow(self.tr('背景颜色'), self.color_button('background_color', self.tr('背景颜色')))
        self.locked = QCheckBox(self.tr('锁定工具栏（不自动隐藏）'))
        self.auto_height = QCheckBox(self.tr('高度随字幕自动调整'))
        self.centered = QCheckBox(self.tr('字幕居中显示'))
        display.addRow(self.centered)
        display.addRow(self.locked)
        display.addRow(self.auto_height)
        self.previous_seconds = QDoubleSpinBox()
        self.previous_seconds.setRange(0, 10)
        self.previous_seconds.setSingleStep(0.5)
        self.previous_seconds.setSuffix(self.tr(' 秒（0 关闭）'))
        self.previous_seconds.setAccessibleName(self.tr('上一句字幕保留秒数'))
        display.addRow(self.tr('上一句保留'), self.previous_seconds)
        self.max_lines = QSpinBox()
        self.max_lines.setRange(1, 4)
        self.max_lines.setAccessibleName(self.tr('字幕正文最多行数'))
        display.addRow(self.tr('正文最多行数（不含注音）'), self.max_lines)
        self.idle_seconds = QDoubleSpinBox()
        self.idle_seconds.setRange(0, 30)
        self.idle_seconds.setSingleStep(.5)
        self.idle_seconds.setSuffix(self.tr(' 秒（0 不清空）'))
        self.idle_seconds.setAccessibleName(self.tr('字幕无新文字后清空秒数'))
        display.addRow(self.tr('无新文字后清空'), self.idle_seconds)
        display.addRow(QLabel(self.tr('鼠标移入浮窗显示工具栏，移出约 1 秒收起。\n'
                             '拖动空白区域移动；边缘可缩放。鼠标穿透可从托盘取消。\n'
                             '显示设置即时生效并自动保存。')))
        self.add_tab(display, self.tr('显示'), scroll=True)
        text = QFormLayout()
        self.font_family = QFontComboBox()
        self.font_family.setAccessibleName(self.tr('字幕字体'))
        text.addRow(self.tr('字体'), self.font_family)
        self.font = QSpinBox()
        self.font.setRange(18, 64)
        self.font.setAccessibleName(self.tr('字幕字号'))
        text.addRow(self.tr('字号'), self.font)
        self.weight = QComboBox()
        for label, value in [(self.tr('常规'), 400), (self.tr('中等'), 500), (self.tr('半粗'), 600), (self.tr('粗体'), 700)]:
            self.weight.addItem(label, value)
        self.weight.setAccessibleName(self.tr('字幕字重'))
        text.addRow(self.tr('字重'), self.weight)
        self.italic = QCheckBox(self.tr('斜体'))
        text.addRow(self.italic)
        text.addRow(self.tr('已确认文字'), self.color_button('stable_color', self.tr('已确认文字颜色')))
        text.addRow(self.tr('未确认文字'), self.color_button('draft_color', self.tr('未确认文字颜色')))
        self.ruby_scale = QSpinBox()
        self.ruby_scale.setRange(25, 80)
        self.ruby_scale.setSuffix('%')
        self.ruby_scale.setAccessibleName(self.tr('注音字号比例'))
        text.addRow(self.tr('注音相对字号'), self.ruby_scale)
        self.line_height = QDoubleSpinBox()
        self.line_height.setRange(1.3, 3)
        self.line_height.setSingleStep(0.1)
        self.line_height.setSuffix(self.tr(' 倍'))
        self.line_height.setAccessibleName(self.tr('字幕行高'))
        text.addRow(self.tr('行高'), self.line_height)
        self.shadow = QCheckBox(self.tr('启用文字阴影'))
        text.addRow(self.shadow)
        text.addRow(self.tr('阴影颜色'), self.color_button('shadow_color', self.tr('文字阴影颜色')))
        self.shadow_opacity = QSpinBox()
        self.shadow_opacity.setRange(0, 100)
        self.shadow_opacity.setSuffix('%')
        self.shadow_opacity.setAccessibleName(self.tr('文字阴影不透明度'))
        text.addRow(self.tr('阴影强度'), self.shadow_opacity)
        self.shadow_blur = QDoubleSpinBox()
        self.shadow_blur.setRange(0, 30)
        self.shadow_blur.setSingleStep(0.5)
        self.shadow_blur.setSuffix(' px')
        self.shadow_blur.setAccessibleName(self.tr('文字阴影模糊半径'))
        text.addRow(self.tr('阴影模糊'), self.shadow_blur)
        self.offset_x = QSpinBox()
        self.offset_y = QSpinBox()
        for widget, axis in [(self.offset_x, self.tr('水平')), (self.offset_y, self.tr('垂直'))]:
            widget.setRange(-20, 20)
            widget.setSuffix(' px')
            widget.setAccessibleName(self.tr('文字阴影水平偏移' if widget is self.offset_x else '文字阴影垂直偏移'))
        offsets = QHBoxLayout()
        offsets.addWidget(QLabel(self.tr('水平')))
        offsets.addWidget(self.offset_x)
        offsets.addWidget(QLabel(self.tr('垂直')))
        offsets.addWidget(self.offset_y)
        text.addRow(self.tr('阴影偏移'), offsets)
        text.addRow(self.tr('描边颜色'), self.color_button('outline_color', self.tr('文字描边颜色')))
        self.outline = QDoubleSpinBox()
        self.outline.setRange(0, 4)
        self.outline.setSingleStep(0.25)
        self.outline.setSuffix(' px')
        self.outline.setAccessibleName(self.tr('文字描边宽度'))
        text.addRow(self.tr('描边宽度（0 关闭）'), self.outline)
        text.addRow(QLabel(self.tr('文字样式即时作用于浮窗并自动保存，无需重启。\n字体同时作用于正文和注音，已确认／未确认颜色仍独立保留。')))
        self.add_tab(text, self.tr('文字'), scroll=True)
        self.refresh_appearance()
        self.opacity.valueChanged.connect(lambda value: self.set_appearance('background_opacity', value))
        self.font.valueChanged.connect(lambda value: self.set_appearance('font_size', value))
        self.locked.toggled.connect(lambda value: self.set_appearance('toolbar_locked', value))
        self.auto_height.toggled.connect(lambda value: self.set_appearance('auto_height', value))
        self.centered.toggled.connect(lambda value: self.set_appearance('centered', value))
        self.previous_seconds.valueChanged.connect(lambda value: self.set_appearance('previous_caption_seconds', value))
        self.max_lines.valueChanged.connect(lambda value: self.set_appearance('max_caption_lines', value))
        self.idle_seconds.valueChanged.connect(lambda value: self.set_appearance('caption_idle_seconds', value))
        self.font_family.currentFontChanged.connect(lambda font: self.set_appearance('font_family', font.family()))
        self.weight.currentIndexChanged.connect(lambda _: self.set_appearance('font_weight', self.weight.currentData()))
        self.italic.toggled.connect(lambda value: self.set_appearance('italic', value))
        self.shadow.toggled.connect(lambda value: self.set_appearance('shadow_enabled', value))
        for widget, key in [(self.ruby_scale, 'ruby_scale'), (self.line_height, 'line_height'),
                            (self.shadow_opacity, 'shadow_opacity'), (self.shadow_blur, 'shadow_blur'),
                            (self.offset_x, 'shadow_offset_x'), (self.offset_y, 'shadow_offset_y'),
                            (self.outline, 'outline_width')]:
            widget.valueChanged.connect(lambda value, key=key: self.set_appearance(key, value))
        self.message = QLabel('')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.pending_notice = QLabel('')
        self.pending_notice.setWordWrap(True)
        pending_row = QHBoxLayout()
        pending_row.addWidget(self.pending_notice, 1)
        layout.addLayout(pending_row)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton(self.tr('应用并重启字幕'))
        self.apply_button.clicked.connect(self.apply_clicked)
        buttons.addWidget(self.apply_button)
        self.discard_button = QPushButton(self.tr('撤销未应用修改'))
        self.discard_button.clicked.connect(self.restore_recognition)
        pending_row.addWidget(self.discard_button)
        self.cancel = QPushButton(self.tr('取消下载'))
        self.cancel.clicked.connect(self.stop_download)
        self.cancel.hide()
        buttons.addWidget(self.cancel)
        close = QPushButton(self.tr('关闭'))
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        quit_button = QPushButton(self.tr('退出字幕程序'))
        quit_button.clicked.connect(self.quit_application)
        buttons.addWidget(quit_button)
        layout.addLayout(buttons)
        self.model.currentIndexChanged.connect(self.update_apply)
        self.source.currentIndexChanged.connect(self.update_apply)
        self.native_backend.currentIndexChanged.connect(self.update_apply)
        for widget in (self.output, self.language, self.whisper_quality):
            widget.currentIndexChanged.connect(self.update_pending)
        for widget in (self.whisper_standard, self.whisper_filter):
            widget.toggled.connect(self.update_pending)
        for widget in (self.native_device, self.chunk_seconds):
            widget.valueChanged.connect(self.update_pending)
        # Snapshot the normalized form, including defaults omitted by older configs.
        self.applied_values = self.values()
        self.tabs.currentChanged.connect(self.tab_changed)
        self.update_apply()
        self.runtime_timer = QTimer(self)
        self.runtime_timer.timeout.connect(self.refresh_runtime_status)
        self.runtime_timer.start(500)
        self.refresh_runtime_status()
        self.interface_language.currentIndexChanged.connect(self.change_ui_language)
        self.retranslate_ui('zh')

    def tr(self, text):
        return translate(text, self.ui_language)

    def change_ui_language(self):
        language = self.interface_language.currentData()
        previous = self.ui_language
        try:
            save_ui_language(self.root, language)
        except (ValueError, OSError):
            self.interface_language.blockSignals(True)
            self.interface_language.setCurrentIndex(self.interface_language.findData(previous))
            self.interface_language.blockSignals(False)
            self.message.setText(self.tr('无法保存面板语言，请稍后重试。'))
            return
        self.ui_language = language
        install_qt_language(language)
        self.retranslate_ui(previous)

    def retranslate_ui(self, previous):
        # Translate existing controls in place: pending downloads, edits, focus,
        # tab selection and recognition choices survive a language switch.
        def converted(text):
            return translate(text, self.ui_language, source_language=previous)
        self.setWindowTitle(converted(self.windowTitle()))
        for widget in self.findChildren(QWidget):
            blocked = widget.blockSignals(True)
            try:
                if isinstance(widget, (QLabel, QPushButton, QCheckBox)):
                    widget.setText(converted(widget.text()))
                if isinstance(widget, QComboBox) and not isinstance(widget, QFontComboBox) and widget is not self.interface_language:
                    for index in range(widget.count()):
                        widget.setItemText(index, converted(widget.itemText(index)))
                if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    widget.setSuffix(converted(widget.suffix()))
                    widget.setSpecialValueText(converted(widget.specialValueText()))
                widget.setAccessibleName(converted(widget.accessibleName()))
                widget.setToolTip(converted(widget.toolTip()))
            finally:
                widget.blockSignals(blocked)
        for index in range(self.tabs.count()):
            self.tabs.setTabText(index, converted(self.tabs.tabText(index)))
        self.update_apply()
        self.refresh_runtime_status()
        self.refresh_color_buttons()
        if self.download is not None and self.download_message:
            template, fields, suffix = self.download_message
            self.message.setText(self.tr(template).format(**fields) + suffix)

    def quit_application(self):
        try:
            self.stop_download()
            request_exit(self.root)
            self.close()
        except OSError:
            self.message.setText(self.tr('退出失败，请使用项目目录中的 Stop.cmd 重试。'))

    def refresh_runtime_status(self):
        self.poll_restart()
        config = read_json(self.root / 'config/caption.json')
        status = read_json(self.root / 'logs/status.json')
        stage = status.get('stage')
        if stage == 'source_error':
            text = status.get('source_note', self.tr('本地识别失败，请检查模型与运行环境'))
        elif stage == 'local_error':
            text = status.get('local_error', self.tr('本地识别失败，请检查模型与运行环境'))
        elif not stage or stage == 'stopped':
            text = self.tr('字幕未运行；可点击“应用并重启字幕”启动。')
        elif stage == 'windows_setup':
            text = self.tr('Windows 字幕已启动，请在系统窗口完成语言包设置并选择日语。')
        elif config.get('recognition_source') == 'windows_livecaptions':
            text = self.tr('Windows 实时字幕 · 识别语言请在系统字幕中设置。')
        elif stage not in ('listening', 'caption_displayed'):
            text = self.tr('正在加载本地模型 · ') + model_label(config.get('local_model', ''))
        else:
            text = self.tr('本地实时识别 · ') + model_label(config.get('local_model', ''))
        self.runtime.setText(self.tr(text))
        self.update_style_controls(config.get('display_mode', 'overlay'))

    def open_windows_captions(self):
        try:
            subprocess.Popen(['LiveCaptions.exe'], creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError:
            self.message.setText(self.tr('无法打开 Windows 实时字幕，需要 Windows 11 22H2 或更新版本。'))

    def tab_changed(self, index):
        self.apply_button.setVisible(index == 0)
        self.style_notice.setVisible(index > 0)

    def update_pending(self, *_):
        dirty = self.values() != self.applied_values
        self.discard_button.setEnabled(dirty and self.download is None and self.restart is None)
        self.discard_button.setVisible(dirty)
        self.pending_notice.setText(self.tr('识别设置有未应用修改；关闭窗口将放弃这些修改。') if dirty else '')
        self.pending_notice.setVisible(dirty)

    def restore_recognition(self):
        """Discard only the pending recognition form, never instant style edits."""
        values = self.applied_values
        controls = ((self.source, 'recognition_source'), (self.output, 'display_mode'),
                    (self.language, 'language'), (self.model, 'local_model'),
                    (self.whisper_quality, 'whisper_draft_beam'),
                    (self.native_backend, 'local_native_backend'))
        widgets = [widget for widget, _ in controls] + [self.whisper_standard, self.whisper_filter,
                                                       self.native_device, self.chunk_seconds]
        for widget in widgets:
            widget.blockSignals(True)
        try:
            for widget, key in controls:
                widget.setCurrentIndex(widget.findData(values[key]))
            self.whisper_standard.setChecked(values['whisper_standard_decode'])
            self.whisper_filter.setChecked(values['whisper_blocklist_enabled'])
            self.native_device.setValue(values['local_native_device'])
            self.chunk_seconds.setValue(values['local_stream_chunk_seconds'])
            self.whisper_phrases = list(values['whisper_blocklist'])
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self.update_apply()

    def closeEvent(self, event):
        self.stop_download()
        if self.restart is None:
            self.restore_recognition()
            self.message.clear()
        event.accept()

    def reject(self):
        # Escape, window X and the Close button share cancellation semantics.
        self.close()

    def update_style_controls(self, output=None):
        output = output or self.config.get('display_mode', 'overlay')
        overlay = output != 'luna'
        for widget in (self.opacity, self.locked, self.auto_height, self.centered,
                       self.font_family, self.font, self.weight, self.italic,
                       self.ruby_scale, self.line_height, self.shadow, self.outline,
                       self.color_buttons['background_color'], self.color_buttons['outline_color']):
            widget.setEnabled(overlay)
        for widget in (self.shadow_opacity, self.shadow_blur, self.offset_x, self.offset_y,
                       self.color_buttons['shadow_color']):
            widget.setEnabled(overlay and self.shadow.isChecked())
        self.style_notice.setText(self.tr('显示与文字设置即时预览并自动保存。') if output == 'overlay' else
            self.tr('Luna 的字体、阴影和背景在 Luna 中调整；双色颜色会实时同步。\n'
                    '上一句保留、正文行数和空闲清空用于两种显示端；其余样式用于独立字幕浮窗。'))

    def add_tab(self, form, label, scroll=False):
        widget = QWidget()
        widget.setLayout(form)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(widget)
            widget = area
        self.tabs.addTab(widget, label)

    def refresh_appearance(self):
        for widget, value in [(self.opacity, self.appearance['background_opacity']),
                              (self.font, self.appearance['font_size']),
                              (self.ruby_scale, self.appearance['ruby_scale']),
                              (self.line_height, self.appearance['line_height']),
                              (self.shadow_opacity, self.appearance['shadow_opacity']),
                              (self.shadow_blur, self.appearance['shadow_blur']),
                              (self.offset_x, self.appearance['shadow_offset_x']),
                              (self.offset_y, self.appearance['shadow_offset_y']),
                              (self.outline, self.appearance['outline_width'])]:
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        for widget, key in ((self.max_lines, 'max_caption_lines'), (self.idle_seconds, 'caption_idle_seconds')):
            widget.blockSignals(True)
            widget.setValue(self.appearance[key])
            widget.blockSignals(False)
        self.previous_seconds.blockSignals(True)
        self.previous_seconds.setValue(self.appearance['previous_caption_seconds'])
        self.previous_seconds.blockSignals(False)
        for widget, key in [(self.locked, 'toolbar_locked'), (self.auto_height, 'auto_height'),
                            (self.centered, 'centered'), (self.italic, 'italic'),
                            (self.shadow, 'shadow_enabled')]:
            widget.blockSignals(True)
            widget.setChecked(self.appearance[key])
            widget.blockSignals(False)
        self.opacity_text.setText(f"{self.appearance['background_opacity']}%")
        self.font_family.blockSignals(True)
        self.font_family.setCurrentFont(QFont(self.appearance['font_family']))
        self.font_family.blockSignals(False)
        self.weight.blockSignals(True)
        self.weight.setCurrentIndex(max(0, self.weight.findData(self.appearance['font_weight'])))
        self.weight.blockSignals(False)
        self.refresh_color_buttons()

    def color_button(self, key, label):
        button = QPushButton()
        button.setAccessibleName(label)
        button.clicked.connect(lambda checked=False: self.choose_color(key))
        self.color_buttons[key] = button
        return button

    def refresh_color_buttons(self):
        for key, button in self.color_buttons.items():
            color = self.appearance[key]
            foreground = '#000000' if QColor(color).lightness() > 140 else '#ffffff'
            button.setText(color.upper() + self.tr('  选择颜色…'))
            button.setStyleSheet(
                f'QPushButton {{background-color:{color};color:{foreground};padding:4px;}}'
                'QPushButton:disabled {background-color:#e5e5e5;color:#888888;}')

    def set_appearance(self, key, value):
        self.appearance_changed(key, value)
        self.opacity_text.setText(f"{self.appearance['background_opacity']}%")
        self.refresh_color_buttons()
        self.update_style_controls(read_json(self.root / 'config/caption.json').get('display_mode', 'overlay'))

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor(self.appearance[key]), self, self.tr('选择颜色'),
                                      QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.set_appearance(key, color.name())

    def values(self):
        return {'recognition_source': self.source.currentData(),
                'language': self.language.currentData(),
                'display_mode': self.output.currentData(),
                'local_model': self.model.currentData(),
                'whisper_draft_beam':self.whisper_quality.currentData(),
                'whisper_standard_decode':self.whisper_standard.isChecked(),
                'local_native_backend': self.native_backend.currentData(),
                'local_native_device': self.native_device.value(),
                'local_stream_chunk_seconds': self.chunk_seconds.value(),
                'whisper_blocklist_enabled': self.whisper_filter.isChecked(),
                'whisper_blocklist': list(self.whisper_phrases)}

    def edit_whisper_blocklist(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr('Whisper 屏蔽词表'))
        dialog.resize(570, 380)
        layout = QVBoxLayout(dialog)
        note = QLabel(self.tr('每行一条，按字面匹配，忽略大小写和空白。不支持正则表达式。\n'
                      '命中内容会从字幕中删除，其他正文保留；真实说出的相同内容也会被删除。\n'
                      '只作用于本地 Whisper 的草稿、最终结果和预读字幕。应用并重启后生效。'))
        note.setWordWrap(True)
        layout.addWidget(note)
        editor = QPlainTextEdit('\n'.join(self.whisper_phrases))
        editor.setAccessibleName(self.tr('Whisper 幻觉屏蔽词表，每行一条'))
        layout.addWidget(editor)
        error = QLabel()
        error.setWordWrap(True)
        layout.addWidget(error)
        buttons = QHBoxLayout()
        defaults = QPushButton(self.tr('恢复默认词表'))
        defaults.clicked.connect(lambda: editor.setPlainText('\n'.join(DEFAULT_WHISPER_BLOCKLIST)))
        buttons.addWidget(defaults)
        save = QPushButton(self.tr('确定'))
        def accept():
            try:
                self.whisper_phrases = validate_blocklist([line.strip() for line in editor.toPlainText().splitlines() if line.strip()])
            except ValueError as problem:
                error.setText(self.tr(str(problem)))
                return
            dialog.accept()
        save.clicked.connect(accept)
        buttons.addWidget(save)
        cancel = QPushButton(self.tr('取消'))
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        dialog.exec()
        self.update_pending()

    def update_apply(self):
        name = self.model.currentData()
        windows = self.source.currentData() == 'windows_livecaptions'
        self.language_label.setText(self.tr('注音语言') if windows else self.tr('识别语言'))
        self.language.setAccessibleName(self.tr('注音语言') if windows else self.tr('STT 识别语言'))
        self.windows_note.setVisible(windows)
        self.windows_settings.setVisible(windows)
        for widget in (self.model, self.chunk_seconds, self.native_backend, self.native_device):
            widget.setEnabled(not windows)
        for index in range(self.model.count()):
            model = self.model.itemData(index)
            suffix = (self.tr('已就绪') if model_ready(self.root, model, self.native_backend.currentData()) else
                      self.tr('需准备运行环境') if model_installed(self.root, model) else self.tr('需下载'))
            self.model.setItemText(index, model_label(model) + ' · ' + suffix)
        self.whisper_filter_row.setVisible(not windows and is_whisper(name))
        show_quality=not windows and is_whisper(name)
        self.whisper_quality.setVisible(show_quality)
        self.whisper_quality_label.setVisible(show_quality)
        self.whisper_standard.setVisible(show_quality)
        native = not windows and backend_for(name) in ('qwen3_asr', 'voxtral_realtime')
        self.native_label.setVisible(native)
        self.native_backend.setVisible(native)
        self.native_device_label.setVisible(native)
        self.native_device.setVisible(native)
        note = EXTRA_MODELS.get(name, {}).get('note', self.tr('Whisper 使用滑动窗口生成实时草稿，支持词汇屏蔽。'))
        if backend_for(name) != 'whisper':
            note += self.tr('\n当前预读时间轴仅支持 Whisper；本模型继续实时识别。')
        self.model_note.setText(self.tr('字幕由 Windows 提供；句末或短暂停顿后标记确认，此确认不是系统模型的 final 事件。') if windows else self.tr(note))
        self.update_pending()
        if self.restart is not None:
            self.apply_button.setText(self.tr('正在重启字幕…'))
            return
        needs_download = not windows and not model_ready(self.root, name, self.native_backend.currentData())
        self.apply_button.setText(self.tr('准备模型与环境并应用') if needs_download else self.tr('应用并重启字幕'))

    def track_restart(self, process, requested_at):
        self.applied_values = self.values()
        self.restart = (process, requested_at, time.monotonic())
        self.tabs.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.update_apply()
        self.message.setText(self.tr('设置已保存，正在重启字幕程序…'))

    def poll_restart(self):
        if self.restart is None:
            return
        process, requested_at, started = self.restart
        code = process.poll()
        if code is not None and code != 0:
            self.finish_restart(self.tr('字幕重启失败，请检查 logs/launcher.stderr.log；模型运行错误见 logs/controller.stderr.log。'))
            return
        runtime = read_json(self.root / 'logs/processes.json')
        status = read_json(self.root / 'logs/status.json')
        # A previous runtime can still publish while the launcher is stopping
        # it. Only accept a ready state from the newly started runtime.
        runtime_started = runtime.get('started_at', 0)
        if (runtime_started >= requested_at and status.get('updated_at', 0) >= runtime_started
                and status.get('stage') in ('local_error', 'source_error')):
            self.finish_restart(status.get('source_note') or status.get('local_error', self.tr('本地模型启动失败，请更换模型或推理设备后重试。')))
            return
        if (code == 0 and runtime_started >= requested_at and status.get('updated_at', 0) >= runtime_started
                and status.get('stage') == 'windows_setup'):
            self.applied_values = self.values()
            self.finish_restart(self.tr('Windows 字幕已启动，请在系统窗口完成语言包设置并选择日语。'))
            return
        if (code == 0 and runtime_started >= requested_at and
                status.get('updated_at', 0) >= runtime_started and
                status.get('stage') in ('listening', 'caption_displayed') and
                status.get('backend') not in (None, 'none', 'loading')):
            self.config.update(read_json(self.root / 'config/caption.json'))
            self.applied_values = self.values()
            self.finish_restart(self.tr('字幕已重启成功。'))
        elif time.monotonic() - started >= 180:
            self.finish_restart(self.tr('等待字幕启动超时，请检查识别状态和 logs/controller.stderr.log；可以重试。'))

    def finish_restart(self, message):
        self.restart = None
        self.tabs.setEnabled(True)
        self.apply_button.setEnabled(True)
        self.update_apply()
        self.message.setText(self.tr(message))

    def apply_clicked(self):
        if self.download is not None or self.restart is not None:
            return
        values = self.values()
        windows = values['recognition_source'] == 'windows_livecaptions'
        if not windows:
            try:
                validate_language(values['local_model'], values['language'])
            except ValueError as error:
                self.message.setText(self.tr(str(error)))
                return
        if windows or model_ready(self.root, values['local_model'], values['local_native_backend']):
            self.apply(values)
            return
        self.pending = values
        self.download_cancelled = False
        self.download_message = None
        self.tabs.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel.show()
        self.message.setText(self.tr('正在下载模型，当前识别继续运行…'))
        self.download = QProcess(self)
        self.update_pending()
        self.download.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.buffer = b''
        self.download.readyReadStandardOutput.connect(self.download_output)
        self.download.finished.connect(self.download_finished)
        self.download.errorOccurred.connect(self.download_error)
        if values['local_model'] in EXTRA_MODELS:
            command = [str(self.root / 'scripts/install_local_model.py'), '--model', values['local_model'],
                       '--native-backend', values['local_native_backend']]
        else:
            command = [str(self.root / 'scripts/fetch_model.py'), '--model', values['local_model']]
        self.download.start(sys.executable, command)

    def download_output(self):
        if self.download is None or self.download_cancelled:
            return
        if isinstance(self.sender(), QProcess) and self.sender() is not self.download:
            return
        self.buffer += bytes(self.download.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
                if 'download_MB' in event:
                    self.download_message = ('模型约 {size} MB，下载期间当前识别继续运行。',
                                             {'size': event['download_MB']}, '')
                    self.message.setText(self.tr(self.download_message[0]).format(**self.download_message[1]))
                if 'downloaded_MB' in event:
                    total = event.get('total_MB')
                    self.download_message = ('正在准备 {model}：已下载 {size} MB',
                        {'model': model_label(self.pending['local_model']), 'size': event['downloaded_MB']},
                        f' / {total} MB' if total else '')
                    self.message.setText(self.tr(self.download_message[0]).format(**self.download_message[1])
                                         + self.download_message[2])
                    if total:
                        self.progress.setRange(0, max(1, total))
                        self.progress.setValue(event['downloaded_MB'])
                if 'total_chunks' in event:
                    self.progress.setRange(0, event['total_chunks'])
                    self.progress.setValue(event['completed_chunks'])
                    if event['completed_chunks'] == event['total_chunks']:
                        self.download_message = None
                        self.message.setText(self.tr('正在校验模型…'))
            except (ValueError, KeyError, TypeError):
                pass

    def download_error(self, error):
        if isinstance(self.sender(), QProcess) and self.sender() is not self.download:
            return
        if error == QProcess.ProcessError.FailedToStart:
            self.download_finished(-1)

    def download_finished(self, code, *_):
        if self.download is None:
            return
        if isinstance(self.sender(), QProcess) and self.sender() is not self.download:
            return
        self.download.deleteLater()
        self.download = None
        self.download_message = None
        self.tabs.setEnabled(True)
        self.apply_button.setEnabled(True)
        self.cancel.hide()
        self.progress.hide()
        self.update_apply()
        if not self.download_cancelled and code == 0 and model_ready(self.root, self.pending['local_model'], self.pending['local_native_backend']):
            self.apply(self.pending)
        else:
            self.message.setText(self.tr('下载未完成，仍使用原来的设置。可以重试，已有进度会保留。'))

    def stop_download(self):
        if self.download:
            # Mark cancellation before termination: finished can arrive with code 0
            # while the user is cancelling a just-completed download.
            self.download_cancelled = True
            process = self.download
            if os.name == 'nt' and process.processId():
                subprocess.run(['taskkill', '/PID', str(process.processId()), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            process.kill()
            process.waitForFinished(1000)
            self.download_finished(-1)
