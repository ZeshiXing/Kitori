"""Desktop subtitle window; local ruby rendering, no browser UI/navigation.

UI method references: LunaTranslator's frameless translator window and its
embedded web renderer. This is independently written Qt glue, not copied GPL code.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import os

from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QEvent, QRect
from PySide6.QtGui import QColor, QPainter, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QToolButton, QFileDialog, QSystemTrayIcon, QMenu, QStyle,
                               QDialog, QPlainTextEdit)
import qtawesome as qta
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from .settings import load_appearance, read_json, write_json, save_recognition
from .preferences import Preferences
from .state import previous_reading_line
from .lifecycle import request_restart


class DragHandle(QLabel):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().windowHandle().startSystemMove()


class Overlay(QWidget):
    def __init__(self, url, token, media=None):
        super().__init__()
        self.url, self.token = url, token
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.root = Path(os.environ.get('JP_CAPTION_ROOT', Path(__file__).resolve().parents[1]))
        self.appearance = load_appearance(self.root)
        self.font_size = self.appearance['font_size']
        self.config = read_json(self.root / 'config/caption.json')
        self.settings_dialog = None
        self.frozen = False
        self.last_state = None
        self.caption_height = 75
        self.history_dialog = None
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_appearance)
        self.last_render = None
        self.page_ready = False
        self.generation = None
        self.pending_play = False
        self.wait_started = None
        self.setWindowTitle('Kitori — 字幕浮窗')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(360, 80)
        self.resize(1000, 130)
        available = QApplication.primaryScreen().availableGeometry()
        self.move(available.x() + max(0, (available.width() - self.width()) // 2),
                  available.bottom() - self.height() - 80)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = QWidget(self)
        layout.addWidget(self.panel)
        inner = QVBoxLayout(self.panel)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        self.toolbar = QWidget(self.panel)
        self.toolbar.setObjectName('captionToolbar')
        self.toolbar.setFixedHeight(30)
        self.toolbar.setStyleSheet(
            'QToolButton {background:transparent;border:0;padding:0;}'
            'QToolButton:hover {background:white;} QToolButton#quit:hover {background:red;}')
        toolbar = QHBoxLayout(self.toolbar)
        toolbar.setContentsMargins(2, 0, 2, 0)
        toolbar.setSpacing(0)
        self.settings_button = self.tool(toolbar, 'cog', '设置', self.show_settings)
        self.freeze_button = self.tool(toolbar, 'pause', '暂停字幕显示（识别继续）', self.toggle_frozen)
        self.tool(toolbar, 'history', '字幕历史', self.show_history)
        self.tool(toolbar, 'copy', '复制当前字幕', self.copy_caption)
        self.tool(toolbar, 'folder-open', '打开媒体并预读', self.choose_media)
        self.play_button = self.tool(toolbar, 'play', '播放本地媒体', self.toggle_media)
        self.play_button.hide()
        drag = DragHandle('')
        drag.setAccessibleName('拖动字幕窗口')
        toolbar.addWidget(drag, 1)
        self.tool(toolbar, 'minus', '减小字号', lambda: self.change_font(-2))
        self.tool(toolbar, 'plus', '增大字号', lambda: self.change_font(2))
        self.background_button = self.tool(toolbar, 'adjust', '切换背景透明', self.toggle_background)
        self.tool(toolbar, 'mouse-pointer', '鼠标穿透（托盘可恢复）', self.enable_passthrough)
        self.pin = self.tool(toolbar, 'thumbtack', '置顶', None, checkable=True)
        self.pin.setChecked(True)
        self.pin.toggled.connect(self.toggle_top)
        self.lock_button = self.tool(toolbar, 'lock', '锁定工具栏', None, checkable=True)
        self.lock_button.setChecked(self.appearance['toolbar_locked'])
        self.lock_button.toggled.connect(lambda value: self.set_appearance('toolbar_locked', value))
        self.tool(toolbar, 'minus-square', '最小化', self.showMinimized)
        self.tool(toolbar, 'times', '退出字幕程序', self.close, name='quit')
        inner.addWidget(self.toolbar)
        self.status = QLabel(self)
        self.status.hide()
        self.view = QWebEngineView(self.panel)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.view.loadFinished.connect(self.on_loaded)
        inner.addWidget(self.view, 1)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_toolbar)
        self.installEventFilter(self)
        self.toolbar.installEventFilter(self)
        self.view.installEventFilter(self)
        self.hide_timer.start(3500)
        QShortcut(QKeySequence('Ctrl+,'), self, activated=self.show_settings)
        render_source = ((Path(__file__).with_name('web') / 'layout.js').read_text(encoding='utf-8') + '\n' +
                         (Path(__file__).with_name('web') / 'app.js').read_text(encoding='utf-8').split('const stream =')[0])
        html = '''<!doctype html><meta charset="utf-8"><style>
        body{margin:0;background:transparent;color:#fff;font-family:"Yu Gothic UI","Segoe UI",sans-serif;overflow:hidden}
        #caption{font-size:30px;line-height:1.8;overflow-wrap:anywhere;padding:6px 10px;text-align:center;
          color:var(--stable,#fff);-webkit-text-stroke:.5px #000;paint-order:stroke fill;
          text-shadow:1px 1px 2px #000,-1px -1px 1px #000}
        rt{font-size:var(--ruby-scale,.45em);color:inherit;-webkit-text-stroke:0}
        .draft{color:var(--draft,#adbcd0)}
        #previous{opacity:.85;margin-bottom:.2em} #previous:empty{display:none}
        </style><div id="caption" lang="ja"><div id="previous"></div><div id="current">等待桌面声音…</div></div><div hidden id="phase"></div>
        <div hidden id="history"></div><div hidden id="connection"></div><script>''' + render_source + '''
        window.setAppearance=(size,a)=>{caption.style.fontSize=size+'px';
          caption.style.textAlign=a.centered?'center':'left';
          caption.style.fontFamily=JSON.stringify(a.font_family)+', "Yu Gothic UI", sans-serif';
          caption.style.fontWeight=a.font_weight;
          caption.style.fontStyle=a.italic?'italic':'normal';
          caption.style.lineHeight=a.line_height;
          caption.style.webkitTextStroke=a.outline_width+'px '+a.outline_color;
          const c=a.shadow_color;
          const rgba='rgba('+parseInt(c.slice(1,3),16)+','+parseInt(c.slice(3,5),16)+','+
            parseInt(c.slice(5,7),16)+','+(a.shadow_opacity/100)+')';
          caption.style.textShadow=a.shadow_enabled?
            a.shadow_offset_x+'px '+a.shadow_offset_y+'px '+a.shadow_blur+'px '+rgba:'none';
          document.body.style.setProperty('--ruby-scale',(a.ruby_scale/100)+'em');
          document.body.style.setProperty('--stable',a.stable_color);
          document.body.style.setProperty('--draft',a.draft_color);};
        window.renderCaption=(line,size,a,previous)=>{setAppearance(size,a);if(line){
          const current=document.getElementById('current');
          const retained=document.getElementById('previous');
          retained.replaceChildren();
          const fitted=fitCaptionRows(line,a.max_caption_lines||2,value=>{renderLine(current,value);return current;});
          if(previous&&fitted.rows<(a.max_caption_lines||2)&&line.text)
            fitCaptionRows(previous,(a.max_caption_lines||2)-fitted.rows,value=>{renderLine(retained,value);return retained;});
          window.captionLayout={rows:fitted.rows+captionBodyRows(retained),trimmed:fitted.trimmed};}
          return Math.ceil(caption.getBoundingClientRect().height);};</script>'''
        self.view.setHtml(html)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.video.setWindowTitle('Kitori — 本地媒体')
        self.video.resize(960, 540)
        self.player.setVideoOutput(self.video)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(150)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.send_clock)
        self.clock_timer.start(250)
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), self)
        menu = QMenu()
        menu.addAction('设置').triggered.connect(self.show_settings)
        restore = menu.addAction('显示字幕并取消鼠标穿透')
        restore.triggered.connect(self.restore_input)
        passthrough = menu.addAction('鼠标穿透')
        passthrough.triggered.connect(self.enable_passthrough)
        quit_action = menu.addAction('退出字幕程序')
        quit_action.triggered.connect(self.close)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('日语字幕：右键可恢复浮窗')
        self.tray.show()
        self.refresh_icons()
        if media:
            QTimer.singleShot(300, lambda: self.open_media(media))

    def tool(self, layout, icon, tip, callback, checkable=False, name=''):
        button = QToolButton(self.toolbar)
        button.setIcon(qta.icon('fa5s.' + icon, color='#2e2eff'))
        button.setProperty('caption_icon', icon)
        button.setIconSize(QSize(20, 20))
        button.setFixedSize(30, 30)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setCheckable(checkable)
        if name:
            button.setObjectName(name)
        if callback:
            button.clicked.connect(callback)
        layout.addWidget(button)
        button.installEventFilter(self)
        return button

    def refresh_icons(self):
        for button in self.toolbar.findChildren(QToolButton):
            active = button.isChecked() or (button is self.freeze_button and self.frozen)
            state = (button.property('caption_icon'), active)
            if getattr(button, '_caption_icon_state', None) != state:
                button.setIcon(qta.icon('fa5s.' + state[0], color='#ff03f2' if active else '#2e2eff'))
                button._caption_icon_state = state

    def on_loaded(self, ok):
        self.page_ready = ok
        for child in self.view.findChildren(QWidget):
            child.installEventFilter(self)
            child.setMouseTracking(True)
        if ok:
            self.render(None)

    def enterEvent(self, event):
        self.show_toolbar()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hide_timer.start(1000)
        super().leaveEvent(event)

    def show_toolbar(self):
        self.hide_timer.stop()
        self.toolbar.show()
        self.adjust_caption_height()
        self.update()

    def hide_toolbar(self):
        if not self.appearance['toolbar_locked'] and not self.underMouse():
            self.toolbar.hide()
            self.adjust_caption_height()
            self.update()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            point = self.mapFromGlobal(event.globalPosition().toPoint())
            edges = Qt.Edge(0)
            if point.x() < 5:
                edges |= Qt.Edge.LeftEdge
            elif point.x() >= self.width() - 5:
                edges |= Qt.Edge.RightEdge
            if point.y() < 5:
                edges |= Qt.Edge.TopEdge
            elif point.y() >= self.height() - 5:
                edges |= Qt.Edge.BottomEdge
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if edges and self.windowHandle().startSystemResize(edges):
                    return True
                if watched is self.view or watched in self.view.findChildren(QWidget):
                    if self.windowHandle().startSystemMove():
                        return True
            if event.type() == QEvent.Type.MouseMove:
                cursor = Qt.CursorShape.ArrowCursor
                if edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
                    cursor = Qt.CursorShape.SizeHorCursor
                elif edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
                    cursor = Qt.CursorShape.SizeVerCursor
                elif edges:
                    cursor = (Qt.CursorShape.SizeFDiagCursor if edges in
                              (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
                              else Qt.CursorShape.SizeBDiagCursor)
                watched.setCursor(cursor)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        if event.size().width() != event.oldSize().width():
            self.last_render = None
        super().resizeEvent(event)

    def toggle_top(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()
        self.refresh_icons()

    def enable_passthrough(self):
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.show()
        self.toolbar.hide()
        self.adjust_caption_height()

    def restore_input(self):
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, False)
        self.showNormal()
        self.show_toolbar()

    def toggle_frozen(self):
        self.frozen = not self.frozen
        self.freeze_button.setProperty('caption_icon', 'play' if self.frozen else 'pause')
        tip = '恢复字幕显示' if self.frozen else '暂停字幕显示（识别继续）'
        self.freeze_button.setAccessibleName(tip)
        self.freeze_button.setToolTip(tip)
        self.last_render = None
        self.refresh_icons()

    def copy_caption(self):
        current = (self.last_state or {}).get('current') or {}
        QApplication.clipboard().setText(current.get('text', ''))

    def show_history(self):
        if self.history_dialog:
            self.history_dialog.close()
        self.history_dialog = QDialog()
        self.history_dialog.setWindowTitle('字幕历史')
        self.history_dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.history_dialog.resize(650, 350)
        layout = QVBoxLayout(self.history_dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        state = self.last_state or {}
        lines = state.get('history', []) + ([state['current']] if state.get('current') else [])
        text.setPlainText('\n\n'.join(line['text'] for line in lines))
        layout.addWidget(text)
        self.history_dialog.show()

    def change_font(self, delta):
        self.set_appearance('font_size', max(18, min(64, self.font_size + delta)))

    def save_appearance(self):
        write_json(self.root / 'config/overlay.json', self.appearance)

    def set_appearance(self, key, value):
        self.appearance[key] = value
        self.font_size = self.appearance['font_size']
        self.last_render = None
        if key == 'toolbar_locked':
            self.lock_button.setChecked(value)
            self.show_toolbar()
            if not value:
                self.hide_timer.start(1000)
        self.refresh_icons()
        self.update()
        self.save_timer.start(350)
        if self.page_ready:
            self.render((self.last_state or {}).get('current'))

    def toggle_background(self):
        opacity = self.appearance['background_opacity']
        self.set_appearance('background_opacity', 0 if opacity else getattr(self, 'previous_opacity', 75))
        if opacity:
            self.previous_opacity = opacity

    def paintEvent(self, event):
        painter = QPainter(self)
        toolbar_height = 30 if self.toolbar.isVisible() else 0
        background = QColor(self.appearance['background_color'])
        background.setAlpha(round(self.appearance['background_opacity'] * 255 / 100))
        painter.fillRect(QRect(0, toolbar_height, self.width(), self.height() - toolbar_height), background)
        if toolbar_height:
            tool_background = QColor(self.appearance['background_color'])
            tool_background.setAlpha(128)
            painter.fillRect(QRect(0, 0, self.width(), toolbar_height), tool_background)

    def render(self, current):
        if not self.page_ready:
            return
        if self.frozen:
            current = None  # Keep the visible text while previewing appearance changes.
        appearance = json.dumps(self.appearance)
        payload = json.dumps(current, ensure_ascii=True)
        previous = json.dumps(previous_reading_line(self.last_state or {}, self.appearance['previous_caption_seconds']), ensure_ascii=True)
        key = (payload, previous, self.font_size, appearance, self.width())
        if key == self.last_render:
            return
        self.last_render = key
        def measured(height):
            if key == self.last_render and isinstance(height, (float, int)):
                self.caption_height = int(height)
                self.adjust_caption_height()
        self.view.page().runJavaScript(f'window.renderCaption({payload},{self.font_size},{appearance},{previous});', measured)

    def adjust_caption_height(self):
        if self.appearance['auto_height']:
            maximum = QApplication.primaryScreen().availableGeometry().height() // 2
            height = max(80, min(maximum, self.caption_height + (30 if self.toolbar.isVisible() else 0) + 4))
            if self.height() != height:
                area = QApplication.primaryScreen().availableGeometry()
                y = max(area.top(), min(self.y() + self.height() - height, area.bottom() - height + 1))
                self.setGeometry(self.x(), y, self.width(), height)

    def show_settings(self):
        if not self.settings_dialog:
            self.settings_dialog = Preferences(self.root, self.config, self.appearance,
                                               self.set_appearance, self.restart_with_settings)
        self.settings_dialog.refresh_appearance()
        self.settings_dialog.show()
        self.settings_dialog.raise_()

    def restart_with_settings(self, values):
        previous = read_json(self.root / 'config/caption.json')
        try:
            config = save_recognition(self.root, values)
            self.save_appearance()
            self.player.pause()
            try:
                requested_at = time.time()
                process = request_restart(self.root, config)
            except OSError:
                write_json(self.root / 'config/caption.json', previous)
                raise
            self.settings_dialog.track_restart(process, requested_at)
        except (OSError, ValueError) as error:
            self.settings_dialog.message.setText(self.settings_dialog.tr(
                str(error) if isinstance(error, ValueError) else '启动失败，仍使用原来的设置。'))

    def post(self, path, data, callback=None):
        request = QNetworkRequest(QUrl(self.url + path))
        request.setRawHeader(b'X-Caption-Token', self.token.encode())
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        reply = self.network.post(request, json.dumps(data).encode())
        def finished():
            try:
                result = json.loads(bytes(reply.readAll()))
                if callback:
                    callback(result)
            except (ValueError, TypeError):
                pass
            reply.deleteLater()
        reply.finished.connect(finished)

    def choose_media(self):
        path, _ = QFileDialog.getOpenFileName(self, '打开要提前识别的媒体', '', '媒体 (*.mp4 *.mkv *.webm *.wav *.mp3 *.flac);;所有文件 (*)')
        if path:
            self.open_media(path)

    def open_media(self, path):
        self.player.pause()
        self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self.play_button.show()
        self.pending_play, self.wait_started = not bool(os.environ.get('JP_CAPTION_NO_AUTOPLAY')), None
        def opened(result):
            self.generation = result.get('generation')
        self.post('/api/lookahead/open', {'source': str(Path(path).resolve())}, opened)
        if Path(path).suffix.lower() in ('.mp4', '.mkv', '.webm', '.mov'):
            self.video.show()

    def toggle_media(self):
        self.pending_play = False
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.duration() and self.player.position() >= self.player.duration() - 100:
                self.player.setPosition(0)
            self.player.play()

    def send_clock(self):
        if self.generation:
            self.post('/api/clock', {'generation': self.generation, 'position': self.player.position() / 1000,
                                   'paused': self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState,
                                   'rate': self.player.playbackRate()})

    def poll(self):
        if self.reply:
            return
        self.reply = self.network.get(QNetworkRequest(QUrl(self.url + '/api/state')))
        self.reply.finished.connect(self.received)

    def received(self):
        reply, self.reply = self.reply, None
        try:
            state = json.loads(bytes(reply.readAll()))
            ahead = state.get('lookahead', {})
            self.last_state = state
            paused = ahead.get('paused', True)
            self.play_button.setProperty('caption_icon', 'play' if paused else 'pause')
            self.play_button.setToolTip('播放本地媒体' if paused else '暂停本地媒体')
            self.refresh_icons()
            if self.pending_play and state.get('backend_ready'):
                self.wait_started = self.wait_started or time.monotonic()
                if ahead.get('lead_seconds', 0) >= 3 or ahead.get('status') in ('unsupported', 'error') or time.monotonic() - self.wait_started > 10:
                    self.pending_play = False
                    self.player.play()
            mode = '提前识别' if state['input_mode'] == 'lookahead' else '实时流式'
            self.status.setText('桌面字幕 · ' + mode + ('' if state.get('backend_ready') else ' · 初始化中') +
                                (f" · 领先 {ahead['lead_seconds']:.1f}s" if state['input_mode'] == 'lookahead' else ''))
            self.settings_button.setToolTip('设置 · ' + self.status.text())
            self.tray.setToolTip(self.status.text() + '；右键恢复浮窗')
            if self.settings_dialog:
                self.config.update(read_json(self.root / 'config/caption.json'))
            self.render(state.get('current'))
        except (ValueError, KeyError, TypeError):
            self.status.setText('日语字幕 · 正在连接')
        reply.deleteLater()

    def closeEvent(self, event):
        self.save_appearance()
        if self.settings_dialog:
            self.settings_dialog.stop_download()
            self.settings_dialog.close()
        if self.history_dialog:
            self.history_dialog.close()
        self.timer.stop()
        self.clock_timer.stop()
        self.player.pause()
        self.video.close()
        self.tray.hide()
        from .lifecycle import request_exit
        try:
            request_exit(self.root)
        except OSError:
            import requests
            try:
                requests.post(self.url + '/api/shutdown', json={}, headers={'X-Caption-Token': self.token}, timeout=0.5)
            except requests.RequestException:
                pass
        event.accept()


def main():
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('--media')
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName('Kitori')
    window = Overlay(os.environ['JP_CAPTION_URL'], os.environ['JP_CAPTION_TOKEN'], args.media)
    window.show()
    sys.exit(app.exec())
