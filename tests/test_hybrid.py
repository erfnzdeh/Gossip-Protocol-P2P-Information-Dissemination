#!/usr/bin/env python3
"""Phase 4a test: compare push-only vs hybrid push-pull gossip.

Runs a 10-node network in both modes, injects a gossip message,
and compares delivery and message overhead.
"""

import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
PYTHON = sys.executable

BASE_PORT_PUSH = 9300
BASE_PORT_HYBRID = 9400
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


def launch_node(port, bootstrap=None, seed=42, mode="push"):
    cmd = [PYTHON, "-m", "gossip",
           "--port", str(port),
           "--fanout", "3",
           "--ttl", "8",
           "--peer-limit", "20",
           "--ping-interval", "1",
           "--peer-timeout", "5",
           "--seed", str(seed),
           "--mode", mode,
           "--pull-interval", "1",
           "--ihave-max-ids", "32"]
    if bootstrap:
        cmd += ["--bootstrap", bootstrap]
    return subprocess.Popen(
        cmd, cwd=ROOT, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def read_log(port):
    path = os.path.join(LOG_DIR, f"node_{port}.log")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""


def count_sent(log_text):
    return len(re.findall(r"SENT \w+", log_text))


def run_test(base_port, mode, label):
    """Run N nodes, inject gossip, return (delivery_count, total_sent)."""
    print(f"\n--- {label} ---")

    # clean logs
    os.makedirs(LOG_DIR, exist_ok=True)
    for f in os.listdir(LOG_DIR):
        os.remove(os.path.join(LOG_DIR, f))

    procs = []
    try:
        procs.append(launch_node(base_port, seed=200, mode=mode))
        time.sleep(0.5)

        seed_addr = f"127.0.0.1:{base_port}"
        for i in range(1, N):
            port = base_port + i
            procs.append(launch_node(port, bootstrap=seed_addr,
                                     seed=200 + i, mode=mode))
            time.sleep(0.15)

        print(f"  waiting 6s for bootstrap ...")
        time.sleep(6)

        # inject gossip
        msg = f"HYBRID_TEST_{mode.upper()}"
        print(f"  injecting: {msg}")
        procs[0].stdin.write((msg + "\n").encode())
        procs[0].stdin.flush()

        # wait for propagation (longer for hybrid to exercise pull)
        wait = 8 if mode == "hybrid" else 5
        print(f"  waiting {wait}s for propagation ...")
        time.sleep(wait)

    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    # count delivery
    delivery = 0
    total_sent = 0
    for i in range(N):
        port = base_port + i
        log = read_log(port)
        total_sent += count_sent(log)
        if ("GOSSIP recv" in log and msg in log) or \
           ("GOSSIP new" in log and msg in log):
            delivery += 1

    print(f"  delivery: {delivery}/{N}")
    print(f"  total messages sent: {total_sent}")
    return delivery, total_sent


def main():
    print("=== Hybrid Push-Pull Test ===")

    push_delivery, push_sent = run_test(BASE_PORT_PUSH, "push", "Push-Only")
    hybrid_delivery, hybrid_sent = run_test(BASE_PORT_HYBRID, "hybrid",
                                             "Hybrid Push-Pull")

    print("\n--- Comparison ---")
    print(f"  Push:   delivery={push_delivery}/{N}  sent={push_sent}")
    print(f"  Hybrid: delivery={hybrid_delivery}/{N}  sent={hybrid_sent}")

    check("push delivery >= 9", push_delivery >= 9)
    check("hybrid delivery >= 9", hybrid_delivery >= 9)
    check("hybrid has more messages (IHAVE/IWANT overhead)",
          hybrid_sent >= push_sent)

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        print("\nFailed — check logs/ for details")
        sys.exit(1)
    else:
        print("All hybrid tests passed!")


if __name__ == "__main__":
    main()
