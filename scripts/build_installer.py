"""Build a small Windows GUI bootstrapper from an explicit public source list."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ('apps/', 'models/', 'downloads/', 'logs/', 'work/', '.venv/', 'dist/', 'build/',
           'docs/experiments/', 'docs/upstream/', '.git/')
PUBLIC_ROOTS = ('jcaption/', 'plugins/', 'scripts/', 'tests/', 'tools/', 'docs/', 'config/', '.github/')
ROOT_FILES = {'README.md', 'README.en.md', 'README.ja.md', 'CONTRIBUTING.md', 'THIRD_PARTY.md',
              'LICENSE', 'pyproject.toml', 'requirements-lock.txt', 'MANIFEST.in', '.gitignore',
              '.editorconfig', '.gitattributes', 'Install.cmd', 'Settings.cmd', 'Stop.cmd',
              'Start-Local.cmd', 'Start-Luna.cmd', 'Start-Both.cmd', 'caption_bridge.py'}


def public_files(root):
    # Whitelist extensions and public roots as well as Git's ignore rules.
    try:
        result = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
                                         cwd=root, text=True, encoding='utf-8', stderr=subprocess.DEVNULL).splitlines()
    except (OSError, subprocess.CalledProcessError):
        # Also reproduce the installer from a source ZIP without a .git directory.
        result = [name for name in ROOT_FILES if (root / name).is_file()]
        for folder in PUBLIC_ROOTS:
            result.extend(p.relative_to(root).as_posix() for p in (root / folder).rglob('*') if p.is_file())
    files = []
    for name in result:
        path = Path(name)
        if name == 'AGENTS.md' or name.startswith(PRIVATE):
            continue
        if name not in ROOT_FILES and not name.startswith(PUBLIC_ROOTS):
            continue
        if name.startswith('config/') and name != 'config/caption.example.json':
            continue
        if path.suffix.lower() not in {'.md', '.py', '.json', '.js', '.html', '.css', '.txt', '.cmd',
                                       '.ps1', '.cs', '.png', '.in', '.toml', '.yml', '.yaml'} and name not in {
                'LICENSE', '.gitignore', '.editorconfig', '.gitattributes'}:
            continue
        if (root / name).is_file():
            files.append(name)
    for name in ['scripts/install.ps1', 'scripts/setup_runtime.py', 'scripts/setup_resources.json',
                 'config/caption.example.json', 'LICENSE', 'THIRD_PARTY.md']:
        if name not in files:
            raise ValueError('Missing required public setup file: ' + name)
    return sorted(files)


def build(output):
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    if not compiler.is_file():
        raise RuntimeError('The Windows .NET Framework C# compiler is required')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jcaption-build-') as temporary:
        payload = Path(temporary) / 'payload.zip'
        files = public_files(ROOT)
        with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as package:
            for name in files:
                package.write(ROOT / name, name)
        command = [str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                   '/out:' + str(output), '/resource:' + str(payload) + ',payload.zip']
        for assembly in ['System.Windows.Forms', 'System.Drawing', 'System.IO.Compression',
                         'System.IO.Compression.FileSystem', 'System.Web.Extensions', 'Microsoft.CSharp']:
            command.append('/reference:' + assembly + '.dll')
        subprocess.run(command + [str(ROOT / 'scripts/setup.cs')], check=True)
        print('Built ' + output.name + ' (' + str(output.stat().st_size) + ' bytes; ' + str(len(files)) + ' public files)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/Kitori-Setup.exe')
    build(parser.parse_args().output)
