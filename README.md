# ClickUp MCP for MCP-compatible agents

Локальный read-only MCP-сервер и skill для работы с задачами ClickUp из Codex, Claude Code, Cursor, VS Code/Copilot, Gemini CLI и других MCP-клиентов.

Он умеет:

- показывать просроченные, сегодняшние и ближайшие задачи;
- находить задачу по ID, URL или названию;
- безопасно сопоставлять задачу с локальным проектом;
- подготавливать prompt для выбранного coding agent;
- по отдельному запросу запускать Codex в новой вкладке Terminal на macOS.

Сервер использует только GET-запросы к ClickUp API v2 и не меняет задачи, статусы или комментарии.

## Требования

- Python 3.10+;
- ClickUp Personal API Token, начинающийся с `pk_`;
- Git — только для клонирования репозитория;
- MCP-клиент. Codex CLI нужен только для автоматической установки в Codex и инструмента запуска Codex.

## Установка и настройка

```bash
git clone https://github.com/stasuik/clickup-mcp.git
cd clickup-mcp
python3 configure.py
```

На Windows используйте `py configure.py`. Скрипт вводит токен скрыто, проверяет `/user` и `/team`, показывает доступные workspace и сохраняет конфигурацию вне репозитория.

Конфигурация по умолчанию хранится в:

```text
~/.config/clickup-mcp/.env
~/.config/clickup-mcp/project_map.json
```

На Windows это соответствует каталогу `.config/clickup-mcp` внутри профиля пользователя. Токены не добавляются в Git.

## Codex

```bash
python3 install.py
```

На Windows:

```powershell
py install.py
```

Установщик регистрирует MCP через `codex mcp add` и копирует skill в `$CODEX_HOME/skills`. Перезапустите Codex после установки.

## Claude, Cursor, VS Code и другие агенты

Установщик может вывести готовый MCP-конфиг с абсолютными путями и текущим Python:

```bash
python3 install.py --print-config
```

На Windows:

```powershell
py install.py --print-config
```

Скопируйте JSON в настройки MCP нужного клиента. Пример результата:

```json
{
  "mcpServers": {
    "clickup": {
      "command": "/path/to/python",
      "args": ["/path/to/clickup-mcp/clickup_mcp_server.py"]
    }
  }
}
```

После подключения skill должен использовать `clickup_task_prompt` для подготовки prompt без запуска процесса. `clickup_launch_codex_for_task` предназначен только для Codex.

## Локальная маршрутизация

В `~/.config/clickup-mcp/project_map.json` задайте соответствие папок названиям списков, папок или задач ClickUp:

```json
{
  "my-project": ["My Project", "Название клиента"]
}
```

Папка `my-project` должна находиться внутри каталога проектов, заданного через `CLICKUP_LOCAL_PROJECTS_ROOT` (по умолчанию `~/localhost-projects`). При неоднозначном совпадении сервер вернёт ошибку и попросит уточнить проект.

## Инструменты MCP

- `clickup_setup` — показать доступные workspace и участников;
- `clickup_current_tasks` — вернуть нормализованные задачи в JSON;
- `clickup_task_summary` — вернуть читаемую сводку по срокам;
- `clickup_route_task` — найти задачу и локальный проект, ничего не запускать;
- `clickup_task_prompt` — подготовить переносимый prompt для любого coding agent;
- `clickup_launch_codex_for_task` — Codex-адаптер с автоматическим запуском Terminal только на macOS.

## Переменные окружения

Поддерживаются `CLICKUP_API_TOKEN` (также `CLICKUP_TOKEN`), `CLICKUP_TEAM_ID`, `CLICKUP_ASSIGNEE_ID`, `CLICKUP_STATUSES`, `CLICKUP_EXCLUDED_STATUSES`, `CLICKUP_LOOKAHEAD_DAYS`, `CLICKUP_LOCAL_PROJECTS_ROOT`, `CLICKUP_PROJECT_MAP`, `CLICKUP_AGENT_BIN` и устаревшая совместимая `CLICKUP_CODEX_BIN`.

`CLICKUP_CONFIG_DIR` меняет каталог конфигурации, `CLICKUP_ENV_FILE` — путь к env-файлу. Переменные окружения имеют приоритет над файлом.

## Проверка

```bash
python3 clickup_agent.py tasks
python3 -m unittest discover -s tests -v
python3 scripts/check_secrets.py
```

Перед запуском с реальными данными можно проверить только handshake MCP — он не обращается к ClickUp до вызова инструмента.

## Обновление и удаление

Обновление:

```bash
git pull
```

После обновления перезапустите MCP-клиент. Удаление регистрации Codex:

```bash
codex mcp remove clickup
```

Пользовательские настройки в `~/.config/clickup-mcp` удаляются отдельно и намеренно не затрагиваются установщиком.

## Секреты

В репозитории нет токенов, персональных workspace/user ID или реальных project mappings. Не добавляйте локальные `.env` и `project_map.json` через `git add -f`.
