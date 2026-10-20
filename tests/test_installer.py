"""Installer boundaries: no private payloads, archive escapes or config resets."""
import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_installer
import setup_runtime


class InstallerTests(unittest.TestCase):
    def test_public_payload_filters_even_tracked_private_records(self):
        required = ['scripts/install.ps1', 'scripts/setup_runtime.py', 'scripts/setup_resources.json',
                    'config/caption.example.json', 'LICENSE', 'THIRD_PARTY.md']
        names = required + ['AGENTS.md', 'docs/experiments/private.md', 'logs/status.json',
                            'config/caption.json', 'config/backup.json', 'private.key',
                            'docs/guides/installation.md']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('example', encoding='utf-8')
            with patch.object(build_installer.subprocess, 'check_output', return_value='\n'.join(names)):
                self.assertEqual(set(build_installer.public_files(root)), set(required + ['docs/guides/installation.md']))

    def test_archive_rejects_windows_and_unix_escapes_before_extracting_anything(self):
        for name in ['../outside', 'C:/outside', '/outside', 'dir/../../outside',
                     'dir\\..\\outside', 'file:stream', 'dir./file', 'dir /file']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with zipfile.ZipFile(root / 'bad.zip', 'w') as archive:
                    archive.writestr('valid.txt', 'must not be extracted')
                    archive.writestr(name, 'bad')
                with self.assertRaises(ValueError):
                    setup_runtime.safe_extract(root / 'bad.zip', root / 'destination')
                self.assertFalse((root / 'destination/valid.txt').exists())

    def test_archive_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            member = zipfile.ZipInfo('link')
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(root / 'bad.zip', 'w') as archive:
                archive.writestr(member, '../outside')
            with self.assertRaises(ValueError):
                setup_runtime.safe_extract(root / 'bad.zip', root / 'output')

    def test_configuration_selects_cpu_without_changing_existing_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/caption.example.json').write_bytes((ROOT / 'config/caption.example.json').read_bytes())
            setup_runtime.initial_configuration(root, 'cpu', 'ja')
            config = json.loads((root / 'config/caption.json').read_text(encoding='utf-8'))
            self.assertEqual((config['device'], config['compute_type'], config['local_model']), ('cpu','int8','small'))
            before = (root / 'config/caption.json').read_bytes()
            ui = (root / 'config/ui.json').read_bytes()
            setup_runtime.initial_configuration(root, 'gpu', 'en')
            self.assertEqual((root / 'config/caption.json').read_bytes(), before)
            self.assertEqual((root / 'config/ui.json').read_bytes(), ui)

    def test_extraction_failure_leaves_no_ready_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / 'incomplete.zip', 'w') as archive:
                archive.writestr('notice.txt','missing executable')
            with patch.object(setup_runtime, 'resource_archive', return_value=root / 'incomplete.zip'):
                with self.assertRaises(RuntimeError):
                    setup_runtime.install_archive({'sha256':'unused','version':'test'},root,root/'runtime',Path('app.exe'))
            self.assertFalse((root/'runtime').exists())
            self.assertFalse(list(root.glob('.setup-*')))

    def test_pinned_source_archive_is_rebased_and_verified_without_changing_files(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root/'source.zip','w') as archive:
                archive.writestr('upstream-commit/src/model.jit', b'upstream model')
            entry={'sha256':'archive-check-is-external','version':'commit',
                   'source_root':'upstream-commit','target_root':'expected-cache-name',
                   'file_checksums':{'src/model.jit':hashlib.sha256(b'upstream model').hexdigest()}}
            with patch.object(setup_runtime,'resource_archive',return_value=root/'source.zip'):
                setup_runtime.install_archive(entry,root,root/'runtime',Path('expected-cache-name/src/model.jit'))
            self.assertEqual((root/'runtime/expected-cache-name/src/model.jit').read_bytes(),b'upstream model')
            self.assertTrue((root/'runtime/.jcaption-resource.json').is_file())

    def test_wrong_model_hash_never_marks_a_runtime_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root/'source.zip','w') as archive:
                archive.writestr('upstream/src/model.jit',b'wrong')
            entry={'sha256':'archive-check-is-external','version':'commit','source_root':'upstream',
                   'target_root':'cache','file_checksums':{'src/model.jit':'0'*64}}
            with patch.object(setup_runtime,'resource_archive',return_value=root/'source.zip'):
                with self.assertRaises(ValueError):
                    setup_runtime.install_archive(entry,root,root/'runtime',Path('cache/src/model.jit'))
            self.assertFalse((root/'runtime').exists())


if __name__ == '__main__':
    unittest.main()
