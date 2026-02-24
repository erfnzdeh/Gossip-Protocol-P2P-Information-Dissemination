#!/usr/bin/env python3
"""Phase 4a test: compare push-only vs hybrid push-pull gossip.

Runs a 10-node network in both modes, injects a gossip message,
and compares delivery and message overhead.
"""

import re
import sys
import time

from helpers import (check, clean_logs, kill_all, launch_node, read_log,
                     reset_counters, summary)

BASE_PORT_PUSH = 9300
BASE_PORT_HYBRID = 9400
N = 10


def count_sent(log_text):
    return len(re.findall(r"SENT \w+", log_text))


def run_test(base_port, mode, label):
    """Run N nodes, inject gossip, return (delivery_count, total_sent)."""
    print(f"\n--- {label} ---")
    clean_logs()

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

        msg = f"HYBRID_TEST_{mode.upper()}"
        print(f"  injecting: {msg}")
        procs[0].stdin.write((msg + "\n").encode())
        procs[0].stdin.flush()

        wait = 8 if mode == "hybrid" else 5
        print(f"  waiting {wait}s for propagation ...")
        time.sleep(wait)
    finally:
        kill_all(procs)

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
    reset_counters()

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

    sys.exit(summary("Hybrid test"))


if __name__ == "__main__":
    main()
