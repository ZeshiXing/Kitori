"""Actual Windows PowerShell 5.1 launcher with isolated fake ASR workers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(os.name == 'nt','Windows PowerShell launcher')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='caption-launch-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root/'scripts').mkdir()
        (self.root/'config').mkdir()
        source = Path(__file__).resolve().parents[1]/'scripts/launch.ps1'
        (self.root/'scripts/launch.ps1').write_bytes(source.read_bytes())
        (self.root/'scripts/stop.ps1').write_text(
            "param([switch]$KeepSettings)\n[IO.File]::WriteAllText((Join-Path $PSScriptRoot '../stopped'), 'yes')",
            encoding='ascii')
        # No external package install, GPU initialization, or user's processes.
        subprocess.run([sys.executable,'-m','venv','--without-pip',str(self.root/'.venv')],
                       check=True,capture_output=True,timeout=30)
        (self.root/'scripts/prepare_runtime.py').write_text('pass\n',encoding='ascii')
        (self.root/'scripts/run_backend.py').write_text(
            'from pathlib import Path\nPath(__file__).resolve().parents[1].joinpath("ready").touch()\n',encoding='ascii')

    def launch(self):
        return subprocess.run(['powershell.exe','-NoProfile','-File',str(self.root/'scripts/launch.ps1'),
                               '-Mode','local','-Display','overlay'],cwd=self.root,
                              capture_output=True,timeout=30)

    def test_utf8_japanese_blocklist_survives_real_ps51_restart(self):
        phrases = ['ご視聴ありがとうございました','ご視聴ありがとうございます','ご視聴']
        config = {'mode':'local','display_mode':'overlay','luna_output_enabled':False,
                  'whisper_blocklist_enabled':True,'whisper_blocklist':phrases}
        path = self.root/'config/caption.json'
        path.write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8')
        outcome = self.launch()
        self.assertEqual(outcome.returncode,0,outcome.stderr.decode(errors='replace'))
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['whisper_blocklist'],phrases)
        until = time.monotonic()+5
        while not (self.root/'ready').exists() and time.monotonic()<until: time.sleep(.05)
        self.assertTrue((self.root/'ready').exists())
        self.assertTrue((self.root/'stopped').exists())

    def test_invalid_config_does_not_stop_the_running_caption_program(self):
        (self.root/'config/caption.json').write_text('{invalid',encoding='utf-8')
        outcome = self.launch()
        self.assertNotEqual(outcome.returncode,0)
        self.assertFalse((self.root/'stopped').exists())
