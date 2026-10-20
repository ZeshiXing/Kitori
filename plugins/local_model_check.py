"""Explicit synthetic diagnostic only; never enabled in the normal capture profile."""
import os
from pathlib import Path
import sys
import Plugins


class LocalModelCheckPlugin(Plugins.Base):
    def init(self):
        if not os.environ.get('JP_CAPTION_CHECK_MODEL'):
            return  # Tiger initializes discovered diagnostic plugins in normal mode too.
        root = Path(os.environ['JP_CAPTION_ROOT'])
        sys.path.insert(0, str(root))
        if os.environ.get('JP_CAPTION_CHECK_SCENARIO') == 'rolling':
            from tools.diagnostics.verify_rolling_asr import check
        else:
            from tools.diagnostics.verify_local_models import check
        check(os.environ['JP_CAPTION_CHECK_MODEL'])
