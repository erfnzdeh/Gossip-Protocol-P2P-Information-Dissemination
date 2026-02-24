"""Shared utilities for manual test scripts."""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
PYTHON = sys.executable

# global counters — reset with reset_counters() between test suites
PASS_COUNT = 0
FAIL_COUNT = 0


def reset_counters():
    global PASS_COUNT, FAIL_COUNT
    PASS_COUNT = 0
    FAIL_COUNT = 0


def check(name: str, condition: bool):
    """Print PASS/FAIL and update global counters."""
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS  {name}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL  {name}")


def summary(label: str = ""):
    """Print final summary and return exit code (0 = all passed)."""
    print(f"\n{'='*40}")
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    if FAIL_COUNT > 0:
        if label:
            print(f"\n{label} — FAILED (check logs/ for details)")
        return 1
    else:
        if label:
            print(f"{label} — all passed!")
        return 0


def clean_logs():
    """Remove all files from the logs directory."""
    os.makedirs(LOG_DIR, exist_ok=True)
    for f in os.listdir(LOG_DIR):
        os.remove(os.path.join(LOG_DIR, f))


def read_log(port: int) -> str:
    """Read the log file for a given node port."""
    path = os.path.join(LOG_DIR, f"node_{port}.log")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""


def launch_node(port: int, *, bootstrap: str = None, seed: int = 42,
                fanout: int = 3, ttl: int = 8, peer_limit: int = 20,
                ping_interval: float = 1, peer_timeout: float = 5,
                mode: str = "push", pull_interval: float = 1,
                ihave_max_ids: int = 32, pow_k: int = 0) -> subprocess.Popen:
    """Launch a gossip node as a subprocess."""
    cmd = [PYTHON, "-m", "gossip",
           "--port", str(port),
           "--fanout", str(fanout),
           "--ttl", str(ttl),
           "--peer-limit", str(peer_limit),
           "--ping-interval", str(ping_interval),
           "--peer-timeout", str(peer_timeout),
           "--seed", str(seed),
           "--mode", mode,
           "--pull-interval", str(pull_interval),
           "--ihave-max-ids", str(ihave_max_ids),
           "--pow-k", str(pow_k)]
    if bootstrap:
        cmd += ["--bootstrap", bootstrap]
    return subprocess.Popen(
        cmd, cwd=ROOT, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def kill_all(procs: list[subprocess.Popen]):
    """Terminate all processes, with kill fallback."""
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
