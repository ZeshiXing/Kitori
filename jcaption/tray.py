"""Settings and shutdown access when Luna is the only caption window."""
from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QStyle, QMessageBox
from .i18n import load_ui_language, translate
from .lifecycle import request_exit


class SessionTray(QObject):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root)
        self.language = None
        self.tray = QSystemTrayIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), self)
        self.menu = QMenu()
        self.settings = self.menu.addAction('')
        self.settings.triggered.connect(self.open_settings)
        self.menu.addSeparator()
        self.exit = self.menu.addAction('')
        self.exit.triggered.connect(self.quit_application)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.activated)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_language)
        self.timer.start(500)
        self.refresh_language()
        self.tray.show()

    def refresh_language(self):
        language = load_ui_language(self.root)
        if language == self.language:
            return
        self.language = language
        self.settings.setText(translate('字幕设置', language))
        self.exit.setText(translate('退出字幕程序', language))
        self.tray.setToolTip(translate('字幕识别', language))

    def activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_settings()

    def open_settings(self):
        subprocess.Popen([sys.executable, str(self.root / 'scripts/caption_settings.py')], cwd=self.root,
                         creationflags=subprocess.CREATE_NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def quit_application(self):
        try:
            request_exit(self.root)
            self.tray.hide()
            QApplication.instance().quit()
        except OSError:
            QMessageBox.warning(None, translate('字幕识别', self.language),
                                translate('退出失败，请使用 Stop.cmd 重试。', self.language))
