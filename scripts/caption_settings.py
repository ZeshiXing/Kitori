"""Native settings can be used even when Luna is the only output window."""
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from jcaption.preferences import Preferences
from jcaption.settings import read_json, write_json, load_appearance, save_recognition
from jcaption.lifecycle import request_restart

ROOT = Path(__file__).resolve().parents[1]
class StandalonePreferences(Preferences):
    def hideEvent(self, event):
        super().hideEvent(event)
        QApplication.instance().quit()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    appearance = load_appearance(ROOT)
    def change(key, value):
        appearance[key] = value
        write_json(ROOT / 'config/overlay.json', appearance)
    def apply(values):
        try:
            config = save_recognition(ROOT, values)
            requested_at = time.time()
            process = request_restart(ROOT, config)
            dialog.track_restart(process, requested_at)
        except (OSError, ValueError) as error:
            dialog.message.setText(dialog.tr(str(error)) if isinstance(error, ValueError) else dialog.tr('无法启动字幕程序。'))
    dialog = StandalonePreferences(ROOT, read_json(ROOT / 'config/caption.json'), appearance, change, apply)
    dialog.refresh_runtime_status()
    dialog.cancel.setVisible(False)
    dialog.finished.connect(app.quit)
    app.aboutToQuit.connect(dialog.stop_download)
    # Preferences normally hides instead of closing because it belongs to an
    # overlay; a standalone invocation should exit with its last visible window.
    dialog.show()
    sys.exit(app.exec())
