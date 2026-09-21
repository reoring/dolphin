#!/usr/bin/env python3
"""Deterministic agent fixture for isolated Dolphin integration tests."""

from __future__ import annotations

import select
import sys
import time

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
