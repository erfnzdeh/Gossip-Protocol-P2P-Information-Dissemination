#!/usr/bin/env python3
"""Phase 2 test: launch 3 nodes, verify they discover each other via bootstrap.

Node 0 (port 9000) is the seed.
Node 1 (port 9001) and Node 2 (port 9002) bootstrap via Node 0.
After a few seconds all three should know about each other.
"""

import os
import re
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
PYTHON = sys.executable

PASS = 0
FAIL = 0


def check(name: str, condition: bool):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def launch_node(port: int, bootstrap: str = None, seed: int = 42) -> subprocess.Popen:
    cmd = [PYTHON, "-m", "gossip",
           "--port", str(port),
           "--ping-interval", "1",
           "--peer-timeout", "4",
           "--seed", str(seed)]
    if bootstrap:
        cmd += ["--bootstrap", bootstrap]
    return subprocess.Popen(
        cmd, cwd=ROOT, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def read_log(port: int) -> str:
    path = os.path.join(LOG_DIR, f"node_{port}.log")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""


def main():
    print("=== Bootstrap test (3 nodes) ===\n")

    # clean old logs
    os.makedirs(LOG_DIR, exist_ok=True)
    for f in os.listdir(LOG_DIR):
        os.remove(os.path.join(LOG_DIR, f))

    procs = []
    try:
        # start seed node
        procs.append(launch_node(9000))
        time.sleep(0.5)

        # start two joining nodes
        procs.append(launch_node(9001, bootstrap="127.0.0.1:9000", seed=43))
        procs.append(launch_node(9002, bootstrap="127.0.0.1:9000", seed=44))

        # wait for peer discovery and ping cycles
        print("  waiting 6s for peer discovery ...")
        time.sleep(6)

    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=3)

    # read logs and check
    log0 = read_log(9000)
    log1 = read_log(9001)
    log2 = read_log(9002)

    print()
    # seed node should have received HELLOs from both joiners
    check("seed saw HELLO from 9001", "HELLO from 127.0.0.1:9001" in log0)
    check("seed saw HELLO from 9002", "HELLO from 127.0.0.1:9002" in log0)

    # joiners should have added the seed as a peer
    check("node 9001 has peer 9000", "peer added   127.0.0.1:9000" in log1)
    check("node 9002 has peer 9000", "peer added   127.0.0.1:9000" in log2)

    # via PEERS_LIST exchange, joiners should discover each other
    check("node 9001 knows about 9002",
          "127.0.0.1:9002" in log1)
    check("node 9002 knows about 9001",
          "127.0.0.1:9001" in log2)

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        print("\nFailed — check logs/ for details")
        sys.exit(1)
    else:
        print("All bootstrap tests passed!")


if __name__ == "__main__":
    main()
