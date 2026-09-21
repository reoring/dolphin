#!/usr/bin/env python3
"""Deterministic agent fixture for isolated Dolphin integration tests."""

from __future__ import annotations

import os
import sys
import time

print("FAKE_AGENT_READY", flush=True)
for line in sys.stdin:
    prompt = line.rstrip("\n")
    print(f"FAKE_AGENT_WORKING {prompt}", flush=True)
    time.sleep(0.05)
    print(f"FAKE_AGENT_DONE {prompt}", flush=True)
