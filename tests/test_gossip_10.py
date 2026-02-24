#!/usr/bin/env python3
"""Phase 2 test: launch 10 nodes, send one gossip message, verify 9+ receive it.

Node 0 (port 9100) is the seed.
Nodes 1-9 (ports 9101-9109) bootstrap via Node 0.
After bootstrap settles, we inject a gossip message into Node 0.
We then check logs to confirm at least 9 of the 10 nodes got it.
"""

import sys
import time

from helpers import (check, clean_logs, kill_all, launch_node, read_log,
                     reset_counters, summary)

BASE_PORT = 9100
N = 10


def main():
    print(f"=== Gossip delivery test ({N} nodes) ===\n")
    reset_counters()
    clean_logs()

    procs = []
    try:
        procs.append(launch_node(BASE_PORT, seed=100))
        time.sleep(0.5)

        seed_addr = f"127.0.0.1:{BASE_PORT}"
        for i in range(1, N):
            procs.append(launch_node(BASE_PORT + i, bootstrap=seed_addr,
                                     seed=100 + i))
            time.sleep(0.15)

        print(f"  waiting 6s for {N} nodes to bootstrap ...")
        time.sleep(6)

        gossip_text = "PHASE2_TEST_MESSAGE"
        print(f"  injecting gossip: {gossip_text}")
        procs[0].stdin.write((gossip_text + "\n").encode())
        procs[0].stdin.flush()

        print("  waiting 5s for gossip propagation ...")
        time.sleep(5)
    finally:
        kill_all(procs)

    received_count = 0
    for i in range(N):
        port = BASE_PORT + i
        log = read_log(port)
        got_it = ("GOSSIP recv" in log and "PHASE2_TEST_MESSAGE" in log) or \
                 ("GOSSIP new" in log and "PHASE2_TEST_MESSAGE" in log)
        if got_it:
            received_count += 1
        print(f"  node {port}: {'received' if got_it else 'MISSED'}")

    print()
    check(f"gossip reached {received_count}/{N} nodes (need >=9)",
          received_count >= 9)
    check("seed node created gossip", "GOSSIP new" in read_log(BASE_PORT))

    for i, p in enumerate(procs):
        port = BASE_PORT + i
        check(f"node {port} no crash", p.returncode in (0, -15, -2, None))

    print(f"\nGossip delivery: {received_count}/{N} nodes")
    sys.exit(summary("Gossip delivery test"))


if __name__ == "__main__":
    main()
