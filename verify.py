"""Run the offline integrated gate from any working directory."""
import ast
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent
for file in root.rglob('*.py'):
    if 'local-evidence' not in file.parts and '__pycache__' not in file.parts:
        ast.parse(file.read_text(encoding='utf-8-sig'), filename=str(file.relative_to(root)))
for name in ('README.md', 'AGENTS.md', 'docs/AGENT_GUIDE.md', 'docs/MAINTENANCE.md', 'NOTICE.md', 'LICENSE', 'LICENSES/srt_fix-Unlicense.txt', 'source-imports.json'):
    if not (root/name).is_file():
        raise SystemExit('Missing maintenance artifact: ' + name)
if sys.platform != 'win32':
    raise SystemExit('The integrated gate requires Windows for actual launcher verification.')
for shell in ('powershell.exe','pwsh.exe'):
    if not shutil.which(shell):
        raise SystemExit('Missing verification shell: ' + shell)
print('Offline gate: Python ' + sys.version.split()[0], flush=True)
raise SystemExit(subprocess.call([sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=root))
