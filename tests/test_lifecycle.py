"""Exit requests invoke the scoped helper; missing helpers never report success."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jcaption.lifecycle import request_exit, request_restart


class LifecycleTests(unittest.TestCase):
    def test_restart_captures_launcher_errors_and_keeps_autoplay_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launch = root/'scripts/launch.ps1'
            launch.parent.mkdir()
            launch.write_text('# fixture',encoding='utf-8')
            with patch('jcaption.lifecycle.subprocess.Popen') as process:
                request_restart(root,{'mode':'local','display_mode':'luna'})
            self.assertEqual(process.call_args.args[0],['powershell.exe','-NoProfile','-File',str(launch),
                                                       '-Mode','local','-Display','luna'])
            self.assertEqual(process.call_args.kwargs['env']['JP_CAPTION_NO_AUTOPLAY'],'1')
            self.assertEqual(Path(process.call_args.kwargs['stderr'].name),root/'logs/launcher.stderr.log')
            self.assertTrue((root/'logs/launcher.stdout.log').exists())

    def test_exit_requests_full_shutdown_with_the_project_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stop = root / 'scripts/stop.ps1'
            stop.parent.mkdir()
            stop.write_text('# fixture',encoding='utf-8')
            with patch('jcaption.lifecycle.subprocess.Popen') as process:
                request_exit(root)
            self.assertEqual(process.call_args.args[0],['powershell.exe','-NoProfile','-File',str(stop)])
            self.assertEqual(process.call_args.kwargs['cwd'],root)

    def test_missing_stop_helper_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('jcaption.lifecycle.subprocess.Popen') as process:
                with self.assertRaises(OSError):
                    request_exit(directory)
            process.assert_not_called()
