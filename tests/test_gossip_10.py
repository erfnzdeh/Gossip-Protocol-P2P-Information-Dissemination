#!/usr/bin/env python3
"""Phase 2 test: launch 10 nodes, send one gossip message, verify 9+ receive it.

Node 0 (port 9100) is the seed.
Nodes 1-9 (ports 9101-9109) bootstrap via Node 0.
After bootstrap settles, we inject a gossip message into Node 0.
We then check logs to confirm at least 9 of the 10 nodes got it.
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
PYTHON = sys.executable

BASE_PORT = 9100
N = 10
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
           "--fanout", "3",
           "--ttl", "8",
           "--peer-limit", "20",
           "--ping-interval", "1",
           "--peer-timeout", "5",
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
    print(f"=== Gossip delivery test ({N} nodes) ===\n")

    # clean old logs
    os.makedirs(LOG_DIR, exist_ok=True)
    for f in os.listdir(LOG_DIR):
        os.remove(os.path.join(LOG_DIR, f))

    procs: list[subprocess.Popen] = []
    try:
        # start seed node
        procs.append(launch_node(BASE_PORT, seed=100))
        time.sleep(0.5)

        # start remaining nodes with staggered bootstrap
        seed_addr = f"127.0.0.1:{BASE_PORT}"
        for i in range(1, N):
            port = BASE_PORT + i
            procs.append(launch_node(port, bootstrap=seed_addr, seed=100 + i))
            time.sleep(0.15)  # slight stagger to reduce contention

        # wait for bootstrap to settle
        print(f"  waiting 6s for {N} nodes to bootstrap ...")
        time.sleep(6)

        # inject gossip from node 0
        gossip_text = "PHASE2_TEST_MESSAGE"
        print(f"  injecting gossip: {gossip_text}")
        procs[0].stdin.write((gossip_text + "\n").encode())
        procs[0].stdin.flush()

        # wait for gossip propagation
        print("  waiting 5s for gossip propagation ...")
        time.sleep(5)

    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    # check how many nodes received the gossip
    received_count = 0
    for i in range(N):
        port = BASE_PORT + i
        log = read_log(port)
        got_it = ("GOSSIP recv" in log and "PHASE2_TEST_MESSAGE" in log) or \
                 ("GOSSIP new" in log and "PHASE2_TEST_MESSAGE" in log)
        if got_it:
            received_count += 1
            status = "received"
        else:
            status = "MISSED"
        print(f"  node {port}: {status}")

    print()
    check(f"gossip reached {received_count}/{N} nodes (need >=9)",
          received_count >= 9)

    # also check seed node created the message
    log0 = read_log(BASE_PORT)
    check("seed node created gossip", "GOSSIP new" in log0)

    # check no crash (all processes terminated cleanly)
    for i, p in enumerate(procs):
        port = BASE_PORT + i
        # returncode -15 is SIGTERM which is expected
        check(f"node {port} no crash",
              p.returncode in (0, -15, -2, None))

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"Gossip delivery: {received_count}/{N} nodes")
    if FAIL > 0:
        print("\nFailed — check logs/ for details")
        sys.exit(1)
    else:
        print("All gossip tests passed!")


if __name__ == "__main__":
    main()
