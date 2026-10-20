"""Tray access for a Luna-only session."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from jcaption.tray import SessionTray

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tray = SessionTray(Path(__file__).resolve().parents[1])
    sys.exit(app.exec())
