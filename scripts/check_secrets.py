"""Scan tracked files without printing matched secret values."""
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
patterns = [r'pk_\d+_[A-Za-z0-9]{15,}', r'gh[pousr]_[A-Za-z0-9]{20,}',
            r'github_pat_[A-Za-z0-9_]{20,}', r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----']
failed = []
for name in filter(None, files):
    path = Path(name)
    if (path.name.startswith('.env') and path.name != '.env.example') or path.name == 'project_map.json':
        failed.append(name)
        continue
    content = (root / name).read_text(errors='replace')
    if any(re.search(pattern, content) for pattern in patterns):
        failed.append(name)
if failed:
    print('FAIL: suspected secrets or personal files: ' + ', '.join(failed))
    raise SystemExit(1)
print(f'PASS: scanned {len(list(filter(None, files)))} tracked files; no recognized secrets.')
