#!/usr/bin/env python3
"""Register MCP and install its skill without copying credentials."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    codex = shutil.which('codex')
    if not codex:
        raise SystemExit('Install Codex CLI and ensure codex is on PATH first.')
    target = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills/clickup-task-runner'
    source = root / 'skills/clickup-task-runner/SKILL.md'
    if target.exists():
        existing = target / 'SKILL.md'
        if not existing.exists() or existing.read_bytes() != source.read_bytes():
            raise SystemExit(f'Skill already exists at {target}; review it before replacing. Nothing changed.')
    result = subprocess.run([codex, 'mcp', 'list', '--json'], check=True, capture_output=True, text=True)
    import json
    if any(item.get('name') == 'clickup' for item in json.loads(result.stdout)):
        raise SystemExit('ClickUp MCP is already configured. Review it with codex mcp get clickup; nothing changed.')
    subprocess.run([codex, 'mcp', 'add', 'clickup', '--', sys.executable, str(root / 'clickup_mcp_server.py')], check=True)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target / 'SKILL.md')
    print('Installed MCP and skill. Restart Codex. Keep this repository at its current path.')


if __name__ == '__main__':
    main()
