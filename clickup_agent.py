#!/usr/bin/env python3
"""Small ClickUp task reporter for MCP-compatible agents."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_BASE = "https://api.clickup.com/api/v2"
CONFIG_DIR = Path(os.environ.get("CLICKUP_CONFIG_DIR", str(Path.home() / ".config/clickup-mcp"))).expanduser()


def load_env(path: Path | None = None) -> None:
    # Load only this integration's explicit config, never another app's secrets.
    path = path or Path(os.environ.get("CLICKUP_ENV_FILE", str(CONFIG_DIR / ".env"))).expanduser()
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if value == "":
        return default
    return value


def require_env(name: str) -> str:
    value = env(name)
    if not value:
        raise SystemExit(f"Missing {name}. Run python3 configure.py to configure ClickUp.")
    return value


def request_json(path: str, params: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    token = env("CLICKUP_API_TOKEN") or env("CLICKUP_TOKEN")
    if not token:
        raise SystemExit("Missing CLICKUP_API_TOKEN. Run python3 configure.py to configure ClickUp.")
    query = urllib.parse.urlencode(params or [])
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(url, headers={"Authorization": token, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        try:
            payload = json.loads(body)
            detail = payload.get("err") or payload.get("ECODE") or payload.get("message")
        except json.JSONDecodeError:
            detail = body[:300]
        suffix = f": {detail}" if detail else ""
        raise SystemExit(
            f"ClickUp API error {exc.code} for {path}{suffix}. "
            "Use a Personal API Token (starts with pk_) without 'Bearer '."
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error while contacting ClickUp: {exc.reason}") from exc


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def excluded_statuses() -> set[str]:
    raw_value = os.environ.get("CLICKUP_EXCLUDED_STATUSES")
    if raw_value is None:
        raw_value = "done"
    return {status.casefold() for status in parse_csv(raw_value)}


def millis(moment: dt.datetime) -> str:
    return str(int(moment.timestamp() * 1000))


def from_millis(value: str | int | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromtimestamp(int(value) / 1000, tz=dt.datetime.now().astimezone().tzinfo)


def fmt_date(value: str | int | None) -> str:
    parsed = from_millis(value)
    if not parsed:
        return "без срока"
    return parsed.strftime("%Y-%m-%d %H:%M" if parsed.hour or parsed.minute else "%Y-%m-%d")


def priority_name(priority: dict[str, Any] | None) -> str:
    if not priority:
        return "нет"
    return str(priority.get("priority") or priority.get("color") or "есть")


def task_url(task: dict[str, Any]) -> str:
    return str(task.get("url") or f"https://app.clickup.com/t/{task.get('id')}")


def assignee_names(task: dict[str, Any]) -> str:
    names = []
    for assignee in task.get("assignees", []):
        names.append(assignee.get("username") or assignee.get("email") or str(assignee.get("id")))
    return ", ".join(names) if names else "не назначено"


def normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    due = from_millis(task.get("due_date"))
    status = task.get("status") or {}
    return {
        "id": task.get("id"),
        "name": task.get("name"),
        "status": status.get("status") or status.get("type") or "без статуса",
        "priority": priority_name(task.get("priority")),
        "due_date": fmt_date(task.get("due_date")),
        "due_timestamp": int(due.timestamp()) if due else None,
        "assignees": assignee_names(task),
        "url": task_url(task),
    }


def fetch_tasks(args: argparse.Namespace) -> list[dict[str, Any]]:
    team_id = require_env("CLICKUP_TEAM_ID")
    now = dt.datetime.now().astimezone()
    lookahead_days = int(env("CLICKUP_LOOKAHEAD_DAYS", "14") or "14")
    until = now + dt.timedelta(days=args.days or lookahead_days)

    params: list[tuple[str, str]] = [
        ("include_closed", "false"),
        ("subtasks", "true"),
        ("order_by", "due_date"),
        ("reverse", "false"),
        ("due_date_lt", millis(until)),
    ]

    assignee_id = env("CLICKUP_ASSIGNEE_ID")
    if assignee_id and not args.all_assignees:
        params.append(("assignees[]", assignee_id))

    for status in parse_csv(env("CLICKUP_STATUSES")):
        params.append(("statuses[]", status))

    tasks: list[dict[str, Any]] = []
    page = 0
    while True:
        response = request_json(f"/team/{team_id}/task", params + [("page", str(page))])
        batch = response.get("tasks", [])
        tasks.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    normalized = [normalize_task(task) for task in tasks]
    excluded = excluded_statuses()
    if not excluded:
        return normalized
    return [task for task in normalized if str(task["status"]).casefold() not in excluded]


def bucket_tasks(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    today = dt.datetime.now().astimezone().date()
    buckets = {"overdue": [], "today": [], "upcoming": [], "no_due": []}
    for task in tasks:
        ts = task["due_timestamp"]
        if ts is None:
            buckets["no_due"].append(task)
            continue
        due_date = dt.datetime.fromtimestamp(ts, tz=dt.datetime.now().astimezone().tzinfo).date()
        if due_date < today:
            buckets["overdue"].append(task)
        elif due_date == today:
            buckets["today"].append(task)
        else:
            buckets["upcoming"].append(task)
    return buckets


def print_task(task: dict[str, Any]) -> None:
    print(f"- {task['name']}")
    print(f"  status: {task['status']} | priority: {task['priority']} | due: {task['due_date']}")
    print(f"  assignees: {task['assignees']}")
    print(f"  url: {task['url']}")


def command_tasks(args: argparse.Namespace) -> None:
    tasks = fetch_tasks(args)
    buckets = bucket_tasks(tasks)
    if args.json:
        print(json.dumps({"count": len(tasks), "buckets": buckets}, ensure_ascii=False, indent=2))
        return

    print(f"Found {len(tasks)} current ClickUp tasks.")
    for key, title in [
        ("overdue", "Overdue"),
        ("today", "Today"),
        ("upcoming", "Upcoming"),
        ("no_due", "No due date"),
    ]:
        print(f"\n{title} ({len(buckets[key])})")
        for task in buckets[key]:
            print_task(task)


def command_setup(_: argparse.Namespace) -> None:
    user_response = request_json("/user")
    current_user = user_response.get("user") or user_response
    if current_user:
        name = current_user.get("username") or current_user.get("email") or "unknown"
        print(f"Current user: {name} | CLICKUP_ASSIGNEE_ID={current_user.get('id')}")

    response = request_json("/team")
    teams = response.get("teams", [])
    if not teams:
        print("No ClickUp workspaces found for this token.")
        return
    for team in teams:
        print(f"\nWorkspace: {team.get('name')} | CLICKUP_TEAM_ID={team.get('id')}")
        for member in team.get("members", []):
            user = member.get("user", {})
            name = user.get("username") or user.get("email") or "unknown"
            print(f"  {name} | CLICKUP_ASSIGNEE_ID={user.get('id')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ClickUp task reporter for MCP-compatible agents.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="List ClickUp workspaces and users.")
    setup.set_defaults(func=command_setup)

    tasks = subparsers.add_parser("tasks", help="Show current ClickUp tasks.")
    tasks.add_argument("--days", type=int, help="Lookahead window in days.")
    tasks.add_argument("--json", action="store_true", help="Print normalized JSON.")
    tasks.add_argument("--all-assignees", action="store_true", help="Do not filter by CLICKUP_ASSIGNEE_ID.")
    tasks.set_defaults(func=command_tasks)
    return parser


def main() -> None:
    load_env()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
