"""Real Windows cleanup: venv children, orphan settings and unrelated apps.

Workers run in a temporary project, so this never stops the user's live app.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


WORKER = '''import os, socket, subprocess, sys, time
from pathlib import Path
root = Path(__file__).resolve().parents[1]
(root/'logs').mkdir(exist_ok=True)
role = Path(__file__).stem
(root/'logs'/(role+'.pid')).write_text(str(os.getpid()))
if role == 'run_backend':
    subprocess.Popen([sys.executable,str(root/'scripts/session_tray.py')])
elif role == 'session_tray':
    subprocess.Popen([sys.executable,str(root/'scripts/caption_settings.py')])
else:
    listener = socket.socket()
    listener.bind(('127.0.0.1',0))
    listener.listen()
    (root/'logs/port').write_text(str(listener.getsockname()[1]))
while True: time.sleep(.1)
'''


@unittest.skipUnless(os.name == 'nt','Windows process lifecycle')
class ShutdownProcessTests(unittest.TestCase):
    def test_restart_preserves_settings_and_exit_cleans_orphans_without_touching_another_project(self):
        with tempfile.TemporaryDirectory() as directory:
            # Windows runners may expose TEMP with an 8.3 alias. Production
            # lifecycle requests resolve their root before starting children.
            temporary_root = Path(directory).resolve()
            root = temporary_root/'caption-project'
            other = temporary_root/'another-project'
            for folder in (root,other):
                (folder/'scripts').mkdir(parents=True)
                (folder/'logs').mkdir()
                for role in ('run_backend','session_tray','caption_settings'):
                    (folder/'scripts'/(role+'.py')).write_text(WORKER,encoding='utf-8')
            original = Path(__file__).resolve().parents[1]/'scripts/stop.ps1'
            (root/'scripts/stop.ps1').write_bytes(original.read_bytes())
            workers = [subprocess.Popen([sys.executable,str(root/'scripts/run_backend.py')]),
                       subprocess.Popen([sys.executable,str(other/'scripts/caption_settings.py')])]
            def ready(folder):
                until = time.monotonic()+8
                while time.monotonic()<until:
                    try:
                        return int((folder/'logs/port').read_text())
                    except (OSError,ValueError): time.sleep(.05)
                self.fail('Worker did not start')
            def listening(port):
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2): return True
                except OSError: return False
            def stop(*args):
                return subprocess.run(['powershell.exe','-NoProfile','-File',str(root/'scripts/stop.ps1'),*args],
                                      capture_output=True,text=True,timeout=20)
            try:
                port, other_port = ready(root),ready(other)
                outcome = stop('-KeepSettings')
                self.assertEqual(outcome.returncode,0,outcome.stderr)
                workers[0].wait(timeout=5)
                self.assertTrue(listening(port),'Restart closed settings opened by the tray')
                self.assertTrue(listening(other_port),'Another project was stopped')
                # The former runtime is gone; settings are now an orphan and
                # there is deliberately no processes.json registry to trust.
                outcome = stop()
                self.assertEqual(outcome.returncode,0,outcome.stderr)
                self.assertFalse(listening(port),'Full exit left orphan settings alive')
                self.assertTrue(listening(other_port),'Full exit stopped another project')
            finally:
                # Ensure temporary test workers never survive a failed assert.
                stop()
                subprocess.run(['taskkill','/PID',str(workers[1].pid),'/T','/F'],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                for worker in workers:
                    try: worker.wait(timeout=5)
                    except subprocess.TimeoutExpired: worker.kill()
