#!/usr/bin/env python3
"""Interactive setup. Credentials are stored outside the Git checkout."""
import getpass
import json
import os
from pathlib import Path
import clickup_agent as api


def main():
    api.load_env()
    token = getpass.getpass('ClickUp personal API token (hidden): ').strip()
    if not token:
        raise SystemExit('Token is required; nothing saved.')
    if not token.startswith('pk_'):
        raise SystemExit(
            "Expected a ClickUp Personal API Token starting with 'pk_'. "
            "Do not paste 'Bearer ', an OAuth token, or an app secret."
        )
    os.environ['CLICKUP_API_TOKEN'] = token
    user = api.request_json('/user')['user']
    teams = api.request_json('/team').get('teams', [])
    if not teams:
        raise SystemExit('No workspaces available; nothing saved.')
    for i, team in enumerate(teams, 1):
        print(f"{i}. {team['name']}")
    choice = input('Workspace number [1]: ').strip() or '1'
    if not choice.isdigit() or not 1 <= int(choice) <= len(teams):
        raise SystemExit('Invalid workspace number; nothing saved.')
    team = teams[int(choice) - 1]
    projects = input('Local projects directory [~/localhost-projects]: ').strip() or '~/localhost-projects'
    values = {'CLICKUP_API_TOKEN': token, 'CLICKUP_TEAM_ID': str(team['id']),
              'CLICKUP_ASSIGNEE_ID': str(user['id']), 'CLICKUP_EXCLUDED_STATUSES': 'done',
              'CLICKUP_LOOKAHEAD_DAYS': '14', 'CLICKUP_LOCAL_PROJECTS_ROOT': str(Path(projects).expanduser().resolve())}
    if any('\n' in v or '\r' in v for v in values.values()):
        raise SystemExit('Values must be single-line; nothing saved.')
    directory = api.CONFIG_DIR
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / '.env'
    if target.exists() and input(f'Replace {target}? [y/N]: ').lower() != 'y':
        raise SystemExit('Nothing saved.')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(target, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(''.join(f'{k}={v}\n' for k, v in values.items()))
    mapping = directory / 'project_map.json'
    if not mapping.exists():
        mapping.write_text('{}\n')
    print(f'Configuration saved to {target}. Token was not added to the repository.')


if __name__ == '__main__':
    main()
