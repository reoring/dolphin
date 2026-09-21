#!/usr/bin/env python3
"""Deterministic agent fixture for isolated Dolphin integration tests."""

from __future__ import annotations

import os
import select
import sys
import time


# Agent input validates the foreground process identity, not only report-agent.
# Re-exec makes the supported hint visible in Linux /proc/<pid>/environ.
if os.environ.get("HERDR_AGENT") != "codex":
    environment = os.environ.copy()
    environment["HERDR_AGENT"] = "codex"
    os.execve(sys.executable, ["python3", *sys.argv], environment)

print("FAKE_AGENT_READY", flush=True)
while True:
    ready, _, _ = select.select([sys.stdin], [], [], 1.0)
    if not ready:
        continue
    line = sys.stdin.readline()
    if not line:
        continue
    prompt = line.rstrip("\n")
    print(f"FAKE_AGENT_WORKING {prompt}", flush=True)
    time.sleep(0.05)
    print(f"FAKE_AGENT_DONE {prompt}", flush=True)
