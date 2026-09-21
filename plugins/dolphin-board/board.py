#!/usr/bin/env python3
"""Small, dependency-free Dolphin workboard for a Herdr overlay pane."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time


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


def render(data: dict) -> str:
    workspaces = data.get("workspaces", [])
    agents = data.get("agents", [])
    by_cwd: dict[str, list[dict]] = {}
    for agent in agents:
        cwd = agent.get("cwd") or agent.get("foreground_cwd") or ""
        by_cwd.setdefault(cwd, []).append(agent)

    lines = [f"{BOLD}DOLPHIN WORKBOARD{RESET}  {DIM}close pane to exit · refresh: 1s{RESET}", ""]
    if not workspaces:
        lines.append(f"{DIM}No workspaces.{RESET}")
        return "\n".join(lines)

    for workspace in workspaces:
        worktree = workspace.get("worktree") or {}
        path = worktree.get("checkout_path", "")
        label = workspace.get("label") or path or workspace.get("workspace_id", "?")
        tabs = workspace.get("tab_count", 0)
        panes = workspace.get("pane_count", 0)
        lines.append(
            f"{BOLD}{'▶' if workspace.get('focused') else ' '} {label}{RESET} "
            f"{DIM}{workspace.get('agent_status', 'unknown')} · {tabs} tabs · {panes} panes{RESET}"
        )
        if path:
            lines.append(f"  {DIM}{path}{RESET}")
        matched = [agent for cwd, values in by_cwd.items() if cwd == path for agent in values]
        for agent in matched:
            name = agent.get("display_agent") or agent.get("agent") or "shell"
            lines.append(f"  {status(agent.get('agent_status'))} {name}  {DIM}{agent.get('pane_id', '')}{RESET}")

    return "\n".join(lines)


def main() -> int:
    while True:
        try:
            sys.stdout.write("\033[2J\033[H" + render(snapshot()) + "\n")
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            sys.stdout.write(f"\033[2J\033[H{BOLD}DOLPHIN WORKBOARD{RESET}\n\n{error}\n")
        sys.stdout.flush()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
