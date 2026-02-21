#!/usr/bin/env python3
"""Phase 3: Run gossip simulations for different network sizes and seeds.

For each N in {10, 20, 50} and each of 5 seeds, this script:
  1. Launches N nodes on localhost (ports BASE_PORT .. BASE_PORT+N-1)
  2. Waits for bootstrap to settle
  3. Injects one GOSSIP message from node 0
  4. Waits for propagation
  5. Copies log files into results/<run_label>/

Usage:
    python scripts/simulate.py                        # full run
    python scripts/simulate.py --sizes 10 --seeds 1   # quick test
    python scripts/simulate.py --fanouts 2 3 5        # vary fanout
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
RESULTS_DIR = os.path.join(ROOT, "results")
PYTHON = sys.executable
BASE_PORT = 9200


def launch_node(port, bootstrap=None, seed=42, fanout=3, ttl=8,
                mode="push", extra_args=None):
    cmd = [PYTHON, "-m", "gossip",
           "--port", str(port),
           "--fanout", str(fanout),
           "--ttl", str(ttl),
           "--peer-limit", "20",
           "--ping-interval", "1",
           "--peer-timeout", "5",
           "--seed", str(seed),
           "--mode", mode]
    if bootstrap:
        cmd += ["--bootstrap", bootstrap]
    if extra_args:
        cmd += extra_args
    return subprocess.Popen(
        cmd, cwd=ROOT, stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def clean_logs():
    os.makedirs(LOG_DIR, exist_ok=True)
    for f in os.listdir(LOG_DIR):
        os.remove(os.path.join(LOG_DIR, f))


def run_trial(n, seed, fanout=3, ttl=8, mode="push", extra_args=None,
              settle_time=None, propagation_time=None):
    """Run one trial: N nodes, one gossip message. Returns log dir path."""
    label = f"N{n}_seed{seed}_fanout{fanout}_ttl{ttl}_{mode}"
    print(f"  trial: {label}")

    clean_logs()

    if settle_time is None:
        settle_time = 3 + n * 0.15  # scale with network size
    if propagation_time is None:
        propagation_time = 3 + n * 0.1

    procs = []
    try:
        # seed node
        procs.append(launch_node(BASE_PORT, seed=seed * 1000, fanout=fanout,
                                 ttl=ttl, mode=mode, extra_args=extra_args))
        time.sleep(0.3)

        # remaining nodes
        seed_addr = f"127.0.0.1:{BASE_PORT}"
        for i in range(1, n):
            port = BASE_PORT + i
            procs.append(launch_node(port, bootstrap=seed_addr,
                                     seed=seed * 1000 + i,
                                     fanout=fanout, ttl=ttl, mode=mode,
                                     extra_args=extra_args))
            time.sleep(0.08)

        # wait for bootstrap
        time.sleep(settle_time)

        # inject gossip
        procs[0].stdin.write(b"SIM_TEST_MSG\n")
        procs[0].stdin.flush()

        # wait for propagation
        time.sleep(propagation_time)

    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    # copy logs to results directory
    dest = os.path.join(RESULTS_DIR, label)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(LOG_DIR, dest)
    return dest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", type=int, nargs="+", default=[10, 20, 50])
    p.add_argument("--seeds", type=int, default=5, help="number of seeds")
    p.add_argument("--fanouts", type=int, nargs="+", default=None,
                   help="fanout values to test (default: just 3)")
    p.add_argument("--ttls", type=int, nargs="+", default=None,
                   help="ttl values to test (default: just 8)")
    p.add_argument("--mode", choices=["push", "hybrid", "both"], default="push")
    args = p.parse_args()

    fanouts = args.fanouts or [3]
    ttls = args.ttls or [8]
    modes = ["push", "hybrid"] if args.mode == "both" else [args.mode]
    seed_list = list(range(1, args.seeds + 1))

    os.makedirs(RESULTS_DIR, exist_ok=True)

    total = len(args.sizes) * len(seed_list) * len(fanouts) * len(ttls) * len(modes)
    done = 0

    print(f"Running {total} trials ...\n")

    for mode in modes:
        for n in args.sizes:
            for fanout in fanouts:
                for ttl in ttls:
                    for seed in seed_list:
                        run_trial(n, seed, fanout=fanout, ttl=ttl, mode=mode)
                        done += 1
                        print(f"    ({done}/{total} done)\n")

    print(f"All {total} trials complete. Results in {RESULTS_DIR}/")
    print("Run: python scripts/analyze.py  to generate charts.")


if __name__ == "__main__":
    main()
