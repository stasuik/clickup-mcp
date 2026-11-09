#!/usr/bin/env python3
"""Register the local MCP server or print a config for another MCP client."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def mcp_config(root: Path) -> dict:
    return {
        "mcpServers": {
            "clickup": {
                "command": sys.executable,
                "args": [str(root / "clickup_mcp_server.py")],
            }
        }
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print a portable MCP JSON config for Claude, Cursor, VS Code, or another client.",
    )
    parser.add_argument(
        "--no-skill",
        action="store_true",
        help="With Codex installation, register MCP without copying the skill.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.print_config:
        print(json.dumps(mcp_config(root), ensure_ascii=False, indent=2))
        return

    codex = shutil.which('codex')
    if not codex:
        raise SystemExit(
            "Codex CLI was not found on PATH. For another agent, run "
            "python install.py --print-config and copy the printed JSON into its MCP settings."
        )
    target = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills/clickup-task-runner'
    source = root / 'skills/clickup-task-runner/SKILL.md'
    if target.exists():
        existing = target / 'SKILL.md'
        if not existing.exists() or existing.read_bytes() != source.read_bytes():
            raise SystemExit(f'Skill already exists at {target}; review it before replacing. Nothing changed.')
    result = subprocess.run([codex, 'mcp', 'list', '--json'], check=True, capture_output=True, text=True)
    if any(item.get('name') == 'clickup' for item in json.loads(result.stdout)):
        raise SystemExit('ClickUp MCP is already configured. Review it with codex mcp get clickup; nothing changed.')
    subprocess.run([codex, 'mcp', 'add', 'clickup', '--', sys.executable, str(root / 'clickup_mcp_server.py')], check=True)
    if not args.no_skill:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target / 'SKILL.md')
    installed = 'MCP' if args.no_skill else 'MCP and skill'
    print(f'Installed {installed}. Restart Codex. Keep this repository at its current path.')


if __name__ == '__main__':
    main()
