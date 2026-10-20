"""Windows caption text -> versioned captions; no audio or credentials involved.

Windows exposes UI text, not word timestamps or final events. Punctuation/idle
commit below is an explicit adapter heuristic, not a model final signal.
"""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time


SOURCE = 'windows_livecaptions'


def reader_executable(root):
    root = Path(root)
    digest = hashlib.sha256((root / 'scripts/windows_captions_reader.cs').read_bytes()).hexdigest()[:12]
    return root / 'apps/WindowsCaptionReader' / digest / 'WindowsCaptionReader.exe'


def prepare_reader(root):
    if sys.platform != 'win32' or sys.getwindowsversion().build < 22621:
        raise ValueError('Windows 实时字幕需要 Windows 11 22H2 或更新版本。')
    root = Path(root)
    source = root / 'scripts/windows_captions_reader.cs'
    target = reader_executable(root)
    if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    compiler = windows / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    refs = []
    for name in ('UIAutomationClient', 'UIAutomationTypes', 'WindowsBase'):
        matches = list((windows / 'Microsoft.NET/assembly/GAC_MSIL' / name).glob('*/' + name + '.dll'))
        if not matches:
            raise ValueError('缺少 Windows UI Automation 运行库。')
        refs.append('/reference:' + str(matches[0]))
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' + str(target),
                             '/reference:System.Web.Extensions.dll', *refs, str(source)],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError('Windows 字幕桥接程序编译失败。')
    return target


class SnapshotStream:
    """Track the consumed offset through revisions and rolling UI windows."""
    def __init__(self, session_id, language='ja', idle_seconds=1.0):
        self.session_id, self.language, self.idle_seconds = session_id, language, idle_seconds
        self.raw = None
        self.start = 0
        self.text = ''
        self.uid, self.revision = 0, 0
        self.changed_at = 0

    def event(self, text, final):
        self.revision += 1
        value = dict(session_id=self.session_id, utterance_id=self.uid, revision=self.revision,
                     text=text, final=final, language=self.language, backend=SOURCE)
        if final:
            self.uid += 1
            self.revision = 0
            self.text = ''
        return value

    def update(self, raw, now=None):
        now = time.monotonic() if now is None else now
        raw = raw.replace('\u200b', '').replace('\r', '')
        raw = re.sub(r'\s*\n\s*', '' if self.language in ('ja', 'zh') else ' ', raw).strip()
        raw = raw[-8000:]
        # Ignore existing text on attach: never replay a previous listening session.
        if self.raw is None:
            self.raw, self.start = raw, len(raw)
            return []
        events = []
        if raw == self.raw:
            if self.text and now - self.changed_at >= self.idle_seconds:
                events.append(self.event(self.text, True))
                self.start = len(raw)
            return events
        old = self.raw
        common = 0
        for a, b in zip(old, raw):
            if a != b: break
            common += 1
        # Growing/revised window, or an older prefix rolling out of the UI.
        threshold = min(8, len(old), len(raw))
        if old and raw and common < threshold:
            overlap = next((size for size in range(min(len(old), len(raw)), 0, -1)
                            if old.endswith(raw[:size])), 0)
            if overlap >= min(8, max(2, len(old) // 3)):
                self.start = max(0, self.start - (len(old) - overlap))
            elif self.start == 0 and self.text:
                pass  # An uncommitted short hypothesis can be completely rewritten.
            else:
                if self.text: events.append(self.event(self.text, True))
                self.start = 0
        if not raw:
            if self.text: events.append(self.event(self.text, True))
            self.start = 0
        self.raw = raw
        self.start = min(self.start, len(raw))
        self.start += len(raw[self.start:]) - len(raw[self.start:].lstrip())
        tail = raw[self.start:].rstrip()
        # Windows can append punctuation after the idle heuristic has already
        # committed the words. A late full stop must not replace that sentence.
        if tail and not any(char.isalnum() for char in tail):
            if self.text:
                events.append(self.event(self.text, True))
            self.start = len(raw)
            self.changed_at = now
            return events
        # Preserve all completed sentences even when one poll receives several.
        while tail:
            match = re.search(r'[。？！!?](?:[」』”"])?', tail)
            if not match: break
            sentence = tail[:match.end()]
            if any(char.isalnum() for char in sentence):
                events.append(self.event(sentence, True))
            self.start += len(sentence)
            self.start += len(raw[self.start:]) - len(raw[self.start:].lstrip())
            tail = raw[self.start:].rstrip()
            if tail and not any(char.isalnum() for char in tail):
                self.start = len(raw)
                tail = ''
        if tail != self.text:
            events.append(self.event(tail, False))
            self.text = tail
        self.changed_at = now
        return events


def run_reader(process, service, root, config, session_id):
    """Consume private IPC; never forward raw snapshots into runtime logs."""
    from caption_bridge import StatusFile
    status = StatusFile(Path(root) / 'logs/status.json')
    stream = SnapshotStream(session_id, config.get('language', 'ja') if config.get('language') != 'auto' else 'ja')
    status(stage='windows_setup', backend=SOURCE, mode=config.get('mode'), streaming=True,
           source=SOURCE, source_note='识别语言请在 Windows 实时字幕中选择；本项目语言用于注音。')
    for line in process.stdout:
        try:
            item = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        kind = item.get('kind')
        if kind in ('snapshot', 'ready'):
            service.backend_ready = True
            for event in stream.update(item.get('text', '')):
                service.state.accept(event)
            status(stage='listening' if not stream.text else 'caption_displayed', backend=SOURCE,
                   source=SOURCE, streaming=True, language=stream.language,
                   source_note='Windows 实时字幕已连接；识别语言在系统字幕中设置，本项目语言用于注音。')
        elif kind in ('setup', 'waiting'):
            status(stage='windows_setup', backend=SOURCE, source=SOURCE,
                   source_note='请在 Windows 实时字幕完成语言包设置，并选择日语。')
        elif kind in ('closed', 'error'):
            service.backend_ready = False
            status(stage='source_error', backend=SOURCE, source=SOURCE,
                   source_note='Windows 实时字幕已关闭或无法读取，请应用并重启字幕。')
