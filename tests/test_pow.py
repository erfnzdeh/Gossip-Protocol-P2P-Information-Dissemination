#!/usr/bin/env python3
"""Phase 4b test: Proof-of-Work computation, validation, and timing.

Tests:
1. PoW computation produces valid results for k=2,3,4
2. Validation accepts valid PoW and rejects invalid ones
3. Timing measurements for different difficulty levels
4. Integration: nodes with PoW can still bootstrap and gossip
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gossip.pow import compute_pow, validate_pow

from helpers import (check, clean_logs, kill_all, launch_node, read_log,
                     reset_counters, summary)


def test_pow_computation():
    print("\n--- PoW computation ---")
    for k in [2, 3, 4]:
        node_id = f"test-node-{k}"
        result = compute_pow(node_id, k)
        check(f"k={k}: has nonce", "nonce" in result)
        check(f"k={k}: digest starts with {'0'*k}",
              result["digest_hex"].startswith("0" * k))
        check(f"k={k}: elapsed_ms > 0", result["elapsed_ms"] >= 0)
        print(f"    k={k}: nonce={result['nonce']}  "
              f"time={result['elapsed_ms']:.1f}ms  "
              f"digest={result['digest_hex'][:16]}...")


def test_pow_validation():
    print("\n--- PoW validation ---")
    node_id = "validation-test-node"
    result = compute_pow(node_id, 3)

    check("valid PoW accepted", validate_pow(node_id, result, 3))
    check("wrong node_id rejected", not validate_pow("wrong-id", result, 3))

    bad_nonce = dict(result, nonce=result["nonce"] + 1)
    check("wrong nonce rejected", not validate_pow(node_id, bad_nonce, 3))
    check("low difficulty rejected", not validate_pow(node_id, result, 10))
    check("None rejected", not validate_pow(node_id, None, 3))
    check("empty dict rejected", not validate_pow(node_id, {}, 3))


def test_pow_timing():
    print("\n--- PoW timing (3 trials each) ---")
    node_id = "timing-test-node"
    print(f"  {'k':>3}  {'mean_ms':>10}  {'min_ms':>10}  {'max_ms':>10}")
    print(f"  {'-'*3}  {'-'*10}  {'-'*10}  {'-'*10}")

    for k in [2, 3, 4, 5]:
        times = []
        for trial in range(3):
            result = compute_pow(f"{node_id}-{trial}", k)
            times.append(result["elapsed_ms"])
        mean_ms = sum(times) / len(times)
        min_ms = min(times)
        max_ms = max(times)
        print(f"  {k:>3}  {mean_ms:>10.1f}  {min_ms:>10.1f}  {max_ms:>10.1f}")
        check(f"k={k} completes in reasonable time", max_ms < 60000)


def test_pow_integration():
    print("\n--- PoW integration (3 nodes with pow_k=3) ---")
    clean_logs()

    procs = []
    try:
        procs.append(launch_node(9500, seed=9500, pow_k=3))
        time.sleep(1)
        procs.append(launch_node(9501, bootstrap="127.0.0.1:9500",
                                 seed=9501, pow_k=3))
        procs.append(launch_node(9502, bootstrap="127.0.0.1:9500",
                                 seed=9502, pow_k=3))
        print("  waiting 8s for PoW + bootstrap ...")
        time.sleep(8)

        procs[0].stdin.write(b"POW_TEST_MSG\n")
        procs[0].stdin.flush()
        time.sleep(3)
    finally:
        kill_all(procs)

    log0 = read_log(9500)
    log1 = read_log(9501)
    log2 = read_log(9502)

    check("seed accepted HELLO from 9501",
          "HELLO from 127.0.0.1:9501" in log0
          and "rejected" not in log0.split("9501")[0][-100:])
    check("node 9501 has peer 9500", "peer added   127.0.0.1:9500" in log1)
    check("node 9502 has peer 9500", "peer added   127.0.0.1:9500" in log2)

    delivery = sum(1 for port in [9500, 9501, 9502]
                   if "POW_TEST_MSG" in read_log(port))
    check(f"gossip reached {delivery}/3 nodes", delivery >= 2)


def test_pow_rejection():
    print("\n--- PoW rejection (node without PoW vs node requiring it) ---")
    clean_logs()

    procs = []
    try:
        procs.append(launch_node(9600, seed=9600, pow_k=4))
        time.sleep(1)
        procs.append(launch_node(9601, bootstrap="127.0.0.1:9600",
                                 seed=9601, pow_k=0))
        time.sleep(4)
    finally:
        kill_all(procs)

    log0 = read_log(9600)
    check("seed rejected HELLO without PoW",
          "rejected" in log0.lower() or "invalid PoW" in log0)
    check("joiner not in seed's peer list",
          "peer added   127.0.0.1:9601" not in log0)


if __name__ == "__main__":
    reset_counters()
    test_pow_computation()
    test_pow_validation()
    test_pow_timing()
    test_pow_integration()
    test_pow_rejection()
    sys.exit(summary("PoW test"))
