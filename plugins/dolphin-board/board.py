#!/usr/bin/env python3
"""Small, dependency-free Dolphin workboard for a Herdr overlay pane."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time

if os.name == "nt":
    import msvcrt
else:
    import select
    import termios
    import tty


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
COLORS = {
    "working": "\033[33m",
    "blocked": "\033[31m",
    "idle": "\033[36m",
    "done": "\033[32m",
    "unknown": "\033[90m",
}


def snapshot() -> dict:
    binary = os.environ.get("HERDR_BIN_PATH", "herdr")
    result = subprocess.run(
        [binary, "api", "snapshot"],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Herdr server unavailable")
    value = json.loads(result.stdout)
    return value.get("snapshot", value.get("result", value))


def status(value: str) -> str:
    value = value or "unknown"
    color = COLORS.get(value, COLORS["unknown"])
    return f"{color}{value.upper():7}{RESET}"


def board_items(data: dict) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    workspaces = data.get("workspaces", [])
    agents = data.get("agents", [])
    for workspace in workspaces:
        items.append(("workspace", workspace.get("workspace_id", "")))
        path = (workspace.get("worktree") or {}).get("checkout_path", "")
        for agent in agents:
            cwd = agent.get("cwd") or agent.get("foreground_cwd") or ""
            if cwd == path and agent.get("pane_id"):
                items.append(("agent", agent["pane_id"]))
    return items


def render(data: dict, selected: int) -> str:
    workspaces = data.get("workspaces", [])
    agents = data.get("agents", [])
    by_cwd: dict[str, list[dict]] = {}
    for agent in agents:
        cwd = agent.get("cwd") or agent.get("foreground_cwd") or ""
        by_cwd.setdefault(cwd, []).append(agent)

    lines = [
        f"{BOLD}DOLPHIN WORKBOARD{RESET}  "
        f"{DIM}↑/↓ select · enter focus · q close · refresh: 1s{RESET}",
        "",
    ]
    if not workspaces:
        lines.append(f"{DIM}No workspaces.{RESET}")
        return "\n".join(lines)

    item_index = 0
    for workspace in workspaces:
        worktree = workspace.get("worktree") or {}
        path = worktree.get("checkout_path", "")
        label = workspace.get("label") or path or workspace.get("workspace_id", "?")
        marker = "▶" if item_index == selected else " "
        lines.append(
            f"{BOLD}{marker} {label}{RESET} "
            f"{DIM}{workspace.get('agent_status', 'unknown')} · "
            f"{workspace.get('tab_count', 0)} tabs · {workspace.get('pane_count', 0)} panes{RESET}"
        )
        item_index += 1
        if path:
            lines.append(f"    {DIM}{path}{RESET}")
        for agent in by_cwd.get(path, []):
            name = agent.get("display_agent") or agent.get("agent") or "shell"
            marker = "▶" if item_index == selected else " "
            lines.append(
                f"  {marker} {status(agent.get('agent_status'))} {name}  "
                f"{DIM}{agent.get('pane_id', '')}{RESET}"
            )
            item_index += 1

    return "\n".join(lines)

def read_key() -> str | None:
    if os.name == "nt":
        if not msvcrt.kbhit():
            return None
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            return {"H": "up", "P": "down"}.get(msvcrt.getwch())
        return key
    ready, _, _ = select.select([sys.stdin], [], [], 0.1)
    if not ready:
        return None
    key = sys.stdin.read(1)
    if key == "\033":
        suffix = sys.stdin.read(2)
        return {"[A": "up", "[B": "down"}.get(suffix, "escape")
    return key


def main() -> int:
    old_settings = None
    if os.name != "nt":
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
    selected = 0
    data: dict = {}
    next_refresh = 0.0
    try:
        while True:
            try:
                if time.monotonic() >= next_refresh:
                    data = snapshot()
                    next_refresh = time.monotonic() + 1.0
                items = board_items(data)
                selected = min(selected, max(0, len(items) - 1))
                sys.stdout.write("\033[2J\033[H" + render(data, selected) + "\n")
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                sys.stdout.write(f"\033[2J\033[H{BOLD}DOLPHIN WORKBOARD{RESET}\n\n{error}\n")
                next_refresh = time.monotonic() + 1.0
            sys.stdout.flush()
            key = read_key()
            if key == "q":
                return 0
            if key in ("j", "down"):
                selected += 1
            elif key in ("k", "up"):
                selected = max(0, selected - 1)
            elif key in ("\r", "\n") and board_items(data):
                kind, target = board_items(data)[selected]
                focus(kind, target)
    finally:
        if old_settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


if __name__ == "__main__":
    raise SystemExit(main())
