"""Install/remove the optional user HTML; run while the selected Luna is stopped."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jcaption.luna import prepare_extension

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--luna-dir', type=Path, default=ROOT / 'apps/LunaTranslator/LunaTranslator_x64')
    parser.add_argument('--disable', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changed = prepare_extension(ROOT, args.luna_dir, args.disable, args.check)
    if args.check:
        raise SystemExit(3 if changed else 0)
    print('Luna user extension ' + ('removed' if args.disable else 'ready') + '; upstream program files unchanged.')
