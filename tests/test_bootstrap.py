#!/usr/bin/env python3
"""Phase 2 test: launch 3 nodes, verify they discover each other via bootstrap.

Node 0 (port 9000) is the seed.
Node 1 (port 9001) and Node 2 (port 9002) bootstrap via Node 0.
After a few seconds all three should know about each other.
"""

import sys
import time

from helpers import (check, clean_logs, kill_all, launch_node, read_log,
                     reset_counters, summary)


def main():
    print("=== Bootstrap test (3 nodes) ===\n")
    reset_counters()
    clean_logs()

    procs = []
    try:
        procs.append(launch_node(9000))
        time.sleep(0.5)
        procs.append(launch_node(9001, bootstrap="127.0.0.1:9000", seed=43))
        procs.append(launch_node(9002, bootstrap="127.0.0.1:9000", seed=44))

        print("  waiting 6s for peer discovery ...")
        time.sleep(6)
    finally:
        kill_all(procs)

    log0 = read_log(9000)
    log1 = read_log(9001)
    log2 = read_log(9002)

    print()
    check("seed saw HELLO from 9001", "HELLO from 127.0.0.1:9001" in log0)
    check("seed saw HELLO from 9002", "HELLO from 127.0.0.1:9002" in log0)
    check("node 9001 has peer 9000", "peer added   127.0.0.1:9000" in log1)
    check("node 9002 has peer 9000", "peer added   127.0.0.1:9000" in log2)
    check("node 9001 knows about 9002", "127.0.0.1:9002" in log1)
    check("node 9002 knows about 9001", "127.0.0.1:9001" in log2)

    sys.exit(summary("Bootstrap test"))


if __name__ == "__main__":
    main()
