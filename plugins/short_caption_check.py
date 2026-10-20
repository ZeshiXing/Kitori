"""Opt-in anime diagnostic: continuous PCM and text remain in bounded RAM."""
import os
from pathlib import Path
import sys
import threading
import Plugins


class ShortCaptionCheckPlugin(Plugins.Base):
    def init(self):
        trial = os.environ.get('JP_CAPTION_SHORT_TRIAL')
        if not trial:
            return
        root = Path(os.environ['JP_CAPTION_ROOT'])
        sys.path.insert(0, str(root))
        from tools.diagnostics.check_short_anime import capture_check
        threading.Thread(target=capture_check, args=(root, trial), daemon=True).start()
