#!/usr/bin/env python3
"""Local MCP server exposing read-only ClickUp workflows to MCP agents."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import clickup_agent


clickup_agent.load_env()

SERVER_INFO = {"name": "local-clickup", "version": "0.2.0"}
LOCAL_PROJECTS_ROOT = Path(os.environ.get("CLICKUP_LOCAL_PROJECTS_ROOT", str(Path.home() / "localhost-projects"))).expanduser()
PROJECT_MAP_PATH = Path(os.environ.get("CLICKUP_PROJECT_MAP", str(clickup_agent.CONFIG_DIR / "project_map.json"))).expanduser()
AGENT_BIN = os.environ.get("CLICKUP_AGENT_BIN") or os.environ.get("CLICKUP_CODEX_BIN", "codex")


def json_text(payload: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ]
    }


def text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def task_line(task: dict[str, Any]) -> str:
    return (
        f"- {task['name']} | {task['status']} | priority: {task['priority']} | "
        f"due: {task['due_date']} | assignees: {task['assignees']} | {task['url']}"
    )


def build_summary(days: int | None = None, all_assignees: bool = False) -> str:
    args = argparse.Namespace(days=days, all_assignees=all_assignees)
    tasks = clickup_agent.fetch_tasks(args)
    buckets = clickup_agent.bucket_tasks(tasks)

    lines = [f"Актуальные задачи ClickUp: {len(tasks)}"]
    sections = [
        ("overdue", "Просрочены"),
        ("today", "На сегодня"),
        ("upcoming", "Ближайшие"),
        ("no_due", "Без срока"),
    ]
    for key, title in sections:
        lines.append(f"\n{title}: {len(buckets[key])}")
        for task in buckets[key]:
            lines.append(task_line(task))
    return "\n".join(lines)


def normalize_text(value: Any) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", str(value or "").casefold())


def load_project_map() -> dict[str, list[str]]:
    if not PROJECT_MAP_PATH.exists():
        return {}
    return json.loads(PROJECT_MAP_PATH.read_text(encoding="utf-8"))


def local_projects() -> list[Path]:
    if not LOCAL_PROJECTS_ROOT.exists():
        return []
    return sorted(path for path in LOCAL_PROJECTS_ROOT.iterdir() if path.is_dir())


def extract_task_id(value: str) -> str | None:
    value = value.strip()
    url_match = re.search(r"/t/([0-9a-zA-Z]+)", value)
    if url_match:
        return url_match.group(1)
    if re.fullmatch(r"[0-9a-zA-Z]{6,}", value):
        return value
    return None


def find_task_by_query(query: str, days: int | None = 365) -> dict[str, Any]:
    task_id = extract_task_id(query)
    if task_id:
        return clickup_agent.request_json(f"/task/{task_id}")

    args = argparse.Namespace(days=days, all_assignees=False)
    tasks = clickup_agent.fetch_tasks(args)
    normalized_query = normalize_text(query)
    scored = []
    for task in tasks:
        name = normalize_text(task.get("name"))
        if normalized_query and normalized_query in name:
            scored.append((1.0, task))
        else:
            scored.append((difflib.SequenceMatcher(None, normalized_query, name).ratio(), task))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < 0.35:
        raise ValueError(f"Task not found for query: {query}")
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.1:
        raise ValueError("Ambiguous task title; use a ClickUp task ID or URL.")
    return clickup_agent.request_json(f"/task/{scored[0][1]['id']}")


def task_location_names(task: dict[str, Any]) -> list[str]:
    names = [task.get("name")]
    for key in ("list", "folder", "project", "space"):
        value = task.get(key)
        if isinstance(value, dict):
            names.append(value.get("name"))
    return [str(name) for name in names if name]


def resolve_project(task: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    projects = local_projects()
    project_map = load_project_map()
    location_names = task_location_names(task)
    normalized_locations = [normalize_text(name) for name in location_names]

    matches = {}
    for dirname, aliases in project_map.items():
        path = (LOCAL_PROJECTS_ROOT / dirname).resolve()
        if not path.is_relative_to(LOCAL_PROJECTS_ROOT.resolve()) or not path.is_dir():
            continue
        for alias in [dirname, *aliases]:
            normalized_alias = normalize_text(alias)
            if any(normalized_alias and normalized_alias in item for item in normalized_locations):
                matches[path] = {"matched_by": alias, "source_names": location_names}
    if len(matches) > 1:
        raise ValueError("Ambiguous local project; refine project_map.json or ask user to choose.")
    if matches:
        return next(iter(matches.items()))

    scored = []
    for path in projects:
        project_key = normalize_text(path.name)
        score = max((difflib.SequenceMatcher(None, project_key, item).ratio() for item in normalized_locations), default=0)
        scored.append((score, path))
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] >= 0.65 and scored[0][0] - scored[1][0] < 0.1:
        raise ValueError("Ambiguous local project; configure explicit aliases.")
    if scored and scored[0][0] >= 0.65:
        return scored[0][1], {"matched_by": scored[0][1].name, "source_names": location_names, "score": scored[0][0]}

    raise ValueError(
        "Could not resolve local project. "
        f"ClickUp names: {location_names}. "
        f"Local projects: {[path.name for path in projects]}"
    )


def task_prompt(task: dict[str, Any], project_path: Path, extra_instructions: str | None = None) -> str:
    status = (task.get("status") or {}).get("status") if isinstance(task.get("status"), dict) else task.get("status")
    due = clickup_agent.fmt_date(task.get("due_date"))
    description = task.get("description") or task.get("text_content") or ""
    parts = [
        "Выполни задачу из ClickUp в этом локальном проекте с помощью подключённого coding agent.",
        "",
        f"Проект: {project_path}",
        f"Задача: {task.get('name')}",
        f"ClickUp ID: {task.get('id')}",
        f"Статус: {status or 'без статуса'}",
        f"Срок: {due}",
        f"Ссылка: {task.get('url') or clickup_agent.task_url(task)}",
    ]
    if description:
        parts.extend(["", "Описание задачи:", description])
    if extra_instructions:
        parts.extend(["", "Дополнительные инструкции:", extra_instructions])
    parts.extend(
        [
            "",
            "Сначала изучи проект и связанные файлы, затем внеси изменения, проверь их и кратко отчитайся.",
        ]
    )
    return "\n".join(parts)


def route_task(arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments.get("task") or arguments.get("query") or arguments.get("task_id")
    if not query:
        raise ValueError("Missing task query or task_id.")
    task = find_task_by_query(str(query), days=arguments.get("days", 365))
    project_path, match = resolve_project(task)
    prompt = task_prompt(task, project_path, arguments.get("extra_instructions"))
    command = f"cd {shlex.quote(str(project_path))} && {shlex.quote(AGENT_BIN)} {shlex.quote(prompt)}"
    return {
        "task": {
            "id": task.get("id"),
            "name": task.get("name"),
            "url": task.get("url") or clickup_agent.task_url(task),
            "list": (task.get("list") or {}).get("name"),
            "folder": (task.get("folder") or {}).get("name"),
        },
        "project_path": str(project_path),
        "match": match,
        "prompt": prompt,
        "command": command,
        "command_args": [AGENT_BIN, prompt],
        "agent_command": AGENT_BIN,
    }


def tool_route_task(arguments: dict[str, Any]) -> dict[str, Any]:
    return json_text(route_task(arguments))


def tool_task_prompt(arguments: dict[str, Any]) -> dict[str, Any]:
    """Prepare a portable agent prompt without starting a process."""
    route = route_task(arguments)
    return json_text(
        {
            "task": route["task"],
            "project_path": route["project_path"],
            "match": route["match"],
            "prompt": route["prompt"],
            "next_step": "Run this prompt in the selected project with the user's preferred agent.",
        }
    )


def tool_launch_codex_for_task(arguments: dict[str, Any]) -> dict[str, Any]:
    route = route_task(arguments)
    command = route["command"]
    dry_run = bool(arguments.get("dry_run", False))
    if not dry_run and sys.platform != "darwin":
        return json_text({"launched": False, "reason": "Automatic Terminal launch is macOS-only; run the returned command manually.", **route})
    if not dry_run:
        script = f'tell application "Terminal"\nactivate\ndo script {json.dumps(command)}\nend tell'
        subprocess.run(["osascript", "-e", script], check=True)
    return json_text({"launched": not dry_run, **route})


def tool_setup(_: dict[str, Any]) -> dict[str, Any]:
    user_response = clickup_agent.request_json("/user")
    current_user = user_response.get("user") or user_response
    response = clickup_agent.request_json("/team")
    teams = []
    for team in response.get("teams", []):
        members = []
        for member in team.get("members", []):
            user = member.get("user", {})
            members.append(
                {
                    "id": user.get("id"),
                    "name": user.get("username") or user.get("email") or "unknown",
                    "email": user.get("email"),
                }
            )
        teams.append({"id": team.get("id"), "name": team.get("name"), "members": members})
    return json_text(
        {
            "current_user": {
                "id": current_user.get("id"),
                "name": current_user.get("username") or current_user.get("email") or "unknown",
                "email": current_user.get("email"),
            },
            "teams": teams,
        }
    )


def tool_current_tasks(arguments: dict[str, Any]) -> dict[str, Any]:
    days = arguments.get("days")
    all_assignees = bool(arguments.get("all_assignees", False))
    args = argparse.Namespace(days=days, all_assignees=all_assignees)
    tasks = clickup_agent.fetch_tasks(args)
    return json_text({"count": len(tasks), "buckets": clickup_agent.bucket_tasks(tasks)})


def tool_task_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    return text_result(
        build_summary(
            days=arguments.get("days"),
            all_assignees=bool(arguments.get("all_assignees", False)),
        )
    )


TOOLS = {
    "clickup_setup": {
        "description": "List available ClickUp workspaces and members for configuration.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_setup,
    },
    "clickup_current_tasks": {
        "description": "Get current ClickUp tasks grouped into overdue, today, upcoming, and no due date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": "Lookahead window in days. Defaults to CLICKUP_LOOKAHEAD_DAYS.",
                },
                "all_assignees": {
                    "type": "boolean",
                    "description": "Ignore CLICKUP_ASSIGNEE_ID and return tasks for all assignees.",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_current_tasks,
    },
    "clickup_task_summary": {
        "description": "Return a readable Russian summary of current ClickUp tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": "Lookahead window in days. Defaults to CLICKUP_LOOKAHEAD_DAYS.",
                },
                "all_assignees": {
                    "type": "boolean",
                    "description": "Ignore CLICKUP_ASSIGNEE_ID and return tasks for all assignees.",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_task_summary,
    },
    "clickup_route_task": {
        "description": "Find a ClickUp task and resolve which local project directory should handle it. Does not launch an agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "ClickUp task ID, URL, or text query matching the task name.",
                },
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": "Search window in days when task is not an ID or URL.",
                },
                "extra_instructions": {
                    "type": "string",
                    "description": "Additional instruction to pass to the launched Codex task.",
                },
            },
            "required": ["task"],
            "additionalProperties": False,
        },
        "handler": tool_route_task,
    },
    "clickup_task_prompt": {
        "description": "Find a ClickUp task, resolve its local project, and prepare a portable prompt for the user's preferred coding agent without launching it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "ClickUp task ID, URL, or text query matching the task name.",
                },
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": "Search window in days when task is not an ID or URL.",
                },
                "extra_instructions": {
                    "type": "string",
                    "description": "Additional instruction to include in the prepared prompt.",
                },
            },
            "required": ["task"],
            "additionalProperties": False,
        },
        "handler": tool_task_prompt,
    },
    "clickup_launch_codex_for_task": {
        "description": "Codex-specific adapter: find a ClickUp task, resolve its local project, and open a new macOS Terminal running Codex with the task prompt. Use clickup_task_prompt for other agents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "ClickUp task ID, URL, or text query matching the task name.",
                },
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": "Search window in days when task is not an ID or URL.",
                },
                "extra_instructions": {
                    "type": "string",
                    "description": "Additional instruction to pass to the launched Codex task.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Return the routing result and command without launching Terminal.",
                },
            },
            "required": ["task"],
            "additionalProperties": False,
        },
        "handler": tool_launch_codex_for_task,
    },
}


def tools_list() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            }
            for name, spec in TOOLS.items()
        ]
    }


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")

    if request_id is None:
        return None

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        elif method == "tools/list":
            result = tools_list()
        elif method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name not in TOOLS:
                raise ValueError(f"Unknown tool: {name}")
            result = TOOLS[name]["handler"](arguments)
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except SystemExit as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    clickup_agent.load_env()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
            )
            continue
        response = handle_request(message)
        if response is not None:
            write_message(response)


if __name__ == "__main__":
    main()
