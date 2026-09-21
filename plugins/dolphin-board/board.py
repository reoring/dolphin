#!/usr/bin/env python3
"""Small, dependency-free Dolphin workboard for a Herdr overlay pane."""

from __future__ import annotations

import json
import os
import select
import shlex
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
    envelope = value.get("result", value)
    return envelope.get("snapshot", envelope)


def status(value: str) -> str:
    value = value or "unknown"
    color = COLORS.get(value, COLORS["unknown"])
    return f"{color}{value.upper():7}{RESET}"


def _workspace_agents(workspace: dict, agents: list[dict]) -> list[dict]:
    workspace_id = workspace.get("workspace_id")
    path = (workspace.get("worktree") or {}).get("checkout_path", "")
    linked = []
    for agent in agents:
        if not agent.get("pane_id"):
            continue
        if agent.get("workspace_id") == workspace_id:
            linked.append(agent)
            continue
        if not agent.get("workspace_id"):
            cwd = agent.get("cwd") or agent.get("foreground_cwd") or ""
            if cwd == path:
                linked.append(agent)
    return linked


def board_items(data: dict) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    workspaces = data.get("workspaces", [])
    agents = data.get("agents", [])
    for workspace in workspaces:
        items.append(("workspace", workspace.get("workspace_id", "")))
        for agent in _workspace_agents(workspace, agents):
            items.append(("agent", agent["pane_id"]))
    return items


def git_summary(path: str) -> str:
    if not path:
        return ""
    result = subprocess.run(
        ["git", "-C", path, "status", "--short"],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    if result.returncode:
        return ""
    changed = len([line for line in result.stdout.splitlines() if line.strip()])
    return f"{changed} changed" if changed else "clean"


def render(data: dict, selected: int, message: str = "") -> str:
    workspaces = data.get("workspaces", [])
    agents = data.get("agents", [])

    lines = [
        f"{BOLD}DOLPHIN WORKBOARD{RESET}  "
        f"{DIM}↑/↓ select · enter focus · n new · p prompt · o output · q close{RESET}",
        "",
    ]
    if message:
        lines.append(f"{DIM}{message}{RESET}")
    if not workspaces:
        lines.append(f"{DIM}No workspaces.{RESET}")
        return "\n".join(lines)

    item_index = 0
    for workspace in workspaces:
        worktree = workspace.get("worktree") or {}
        path = worktree.get("checkout_path", "")
        branch = worktree.get("branch") or "detached"
        label = workspace.get("label") or path or workspace.get("workspace_id", "?")
        marker = "▶" if item_index == selected else " "
        lines.append(
            f"{BOLD}{marker} {label}{RESET} "
            f"{DIM}{branch} · {workspace.get('agent_status', 'unknown')} · "
            f"{workspace.get('tab_count', 0)} tabs · "
            f"{workspace.get('pane_count', 0)} panes · {git_summary(path)}{RESET}"
        )
        item_index += 1
        if path:
            lines.append(f"    {DIM}{path}{RESET}")
        for agent in _workspace_agents(workspace, agents):
            name = agent.get("display_agent") or agent.get("agent") or "shell"
            marker = "▶" if item_index == selected else " "
            lines.append(
                f"  {marker} {status(agent.get('agent_status'))} {name}  "
                f"{DIM}{agent.get('pane_id', '')}{RESET}"
            )
            item_index += 1

    return "\n".join(lines)


def focus(kind: str, target: str) -> str:
    binary = os.environ.get("HERDR_BIN_PATH", "herdr")
    command = ["workspace", "focus", target] if kind == "workspace" else ["agent", "focus", target]
    result = subprocess.run([binary, *command], check=False, capture_output=True, text=True, timeout=5)
    if result.returncode:
        return result.stderr.strip() or f"Focus failed: {target}"
    return f"Focused {target}"

def new_task(workspace: dict, old_settings: list[int] | None) -> str:
    if old_settings is not None:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    try:
        sys.stdout.write("\nNew branch: ")
        sys.stdout.flush()
        branch = input().strip()
    except (EOFError, KeyboardInterrupt):
        return "New task cancelled"
    finally:
        if old_settings is not None:
            tty.setcbreak(sys.stdin.fileno())
    if not branch:
        return "New task cancelled"

    worktree = workspace.get("worktree") or {}
    cwd = worktree.get("checkout_path") or workspace.get("cwd") or ""
    if not cwd:
        return "New task failed: workspace cwd unavailable"

    binary = os.environ.get("HERDR_BIN_PATH", "herdr")
    result = subprocess.run(
        [
            binary,
            "worktree",
            "create",
            "--cwd",
            cwd,
            "--branch",
            branch,
            "--label",
            branch,
            "--focus",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode:
        return result.stderr.strip() or "Worktree create failed"
    try:
        value = json.loads(result.stdout)
        payload = value.get("result", value)
        workspace_id = payload["workspace"]["workspace_id"]
        payload["worktree"]["path"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return result.stderr.strip() or "Worktree create returned invalid JSON"

    agent_command = os.environ.get("DOLPHIN_AGENT_COMMAND", "").strip()
    if not agent_command:
        return f"Created {branch} ({workspace_id})"

    try:
        refreshed = snapshot()
        root_pane = next(
            pane["pane_id"]
            for pane in refreshed.get("panes", [])
            if pane.get("workspace_id") == workspace_id
        )
    except (KeyError, StopIteration, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        return f"Created {branch} ({workspace_id}); root pane unavailable: {error}"

    try:
        command = shlex.split(agent_command)
    except ValueError as error:
        return str(error)
    if command:
        agent_result = subprocess.run(
            [binary, "pane", "run", root_pane, *command],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if agent_result.returncode:
            return agent_result.stderr.strip() or "Agent start failed"
    return f"Created {branch} ({workspace_id})"


def submit_prompt(target: str, old_settings: list[int] | None) -> str:
    if old_settings is not None:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    try:
        sys.stdout.write("\nPrompt: ")
        sys.stdout.flush()
        text = input()
    except (EOFError, KeyboardInterrupt):
        return "Prompt cancelled"
    finally:
        if old_settings is not None:
            tty.setcbreak(sys.stdin.fileno())
    if not text.strip():
        return "Prompt ignored: empty input"
    binary = os.environ.get("HERDR_BIN_PATH", "herdr")
    result = subprocess.run(
        [binary, "agent", "prompt", target, text],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        return result.stderr.strip() or "Prompt failed"
    return f"Prompt submitted to {target}"


def output_preview(target: str) -> str:
    binary = os.environ.get("HERDR_BIN_PATH", "herdr")
    result = subprocess.run(
        [
            binary,
            "agent",
            "read",
            target,
            "--source",
            "visible",
            "--lines",
            "8",
            "--format",
            "text",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode:
        return result.stderr.strip() or "Output read failed"
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    text = " ".join(lines)
    return f"Output: {text[-180:]}" if text else "Output: empty"

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
    selected_item: tuple[str, str] | None = None
    message = ""
    data: dict = {}
    next_refresh = 0.0
    try:
        while True:
            try:
                if time.monotonic() >= next_refresh:
                    data = snapshot()
                    items = board_items(data)
                    if selected_item in items:
                        selected = items.index(selected_item)
                    else:
                        selected = min(selected, max(0, len(items) - 1))
                    next_refresh = time.monotonic() + 1.0
                items = board_items(data)
                selected = min(selected, max(0, len(items) - 1))
                selected_item = items[selected] if items else None
                sys.stdout.write("\033[2J\033[H" + render(data, selected, message) + "\n")
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                sys.stdout.write(f"\033[2J\033[H{BOLD}DOLPHIN WORKBOARD{RESET}\n\n{error}\n")
                next_refresh = time.monotonic() + 1.0
            sys.stdout.flush()
            key = read_key()
            if key == "q":
                return 0
            if key in ("j", "down"):
                selected = min(selected + 1, max(0, len(items) - 1))
                message = ""
            elif key in ("k", "up"):
                selected = max(0, selected - 1)
                message = ""
            elif key in ("\r", "\n") and items:
                message = focus(*items[selected])
            elif key == "p" and items:
                kind, target = items[selected]
                message = submit_prompt(target, old_settings) if kind == "agent" else "Select an agent to send a prompt"
            elif key == "n" and items:
                kind, target = items[selected]
                if kind == "workspace":
                    workspace = next(
                        workspace
                        for workspace in data.get("workspaces", [])
                        if workspace.get("workspace_id") == target
                    )
                    if not (workspace.get("worktree") or {}).get("checkout_path"):
                        pane = next(
                            pane
                            for pane in data.get("panes", [])
                            if pane.get("workspace_id") == target
                        )
                        workspace = {
                            **workspace,
                            "cwd": pane.get("cwd") or pane.get("foreground_cwd") or "",
                        }
                    message = new_task(workspace, old_settings)
                else:
                    message = "Select a workspace to start a new task"
            elif key == "o" and items:
                kind, target = items[selected]
                message = output_preview(target) if kind == "agent" else "Select an agent to read output"
    finally:
        if old_settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


if __name__ == "__main__":
    raise SystemExit(main())
