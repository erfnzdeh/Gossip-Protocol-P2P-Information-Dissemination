#!/usr/bin/env python3
"""Phase 3: Parse simulation logs and generate performance charts.

Reads results/ directory produced by simulate.py.
Computes convergence time, message overhead, and generates matplotlib charts.

Usage:
    python scripts/analyze.py
"""

import os
import re
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, "results")
CHARTS_DIR = os.path.join(ROOT, "charts")


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

# Log line format: HH:MM:SS.mmm [PORT] [EPOCH_MS] MESSAGE
LINE_RE = re.compile(
    r"[\d:.]+\s+\[(\d+)\]\s+\[(\d+)\]\s+(.*)"
)

GOSSIP_RECV_RE = re.compile(r"GOSSIP recv\s+msg_id=(\S+)")
GOSSIP_NEW_RE = re.compile(r"GOSSIP new\s+msg_id=(\S+)")
STATS_RE = re.compile(r"STATS sent=(\d+)")
SENT_RE = re.compile(r"SENT (\S+) ->")


def parse_trial(trial_dir):
    """Parse all log files in a trial directory.

    Returns:
        gossip_events: list of (epoch_ms, port, msg_id, event_type)
        sent_events:   list of (epoch_ms, msg_type_str)
        n_nodes:       number of nodes in the trial
    """
    gossip_events = []
    sent_events = []
    ports = set()

    for fname in sorted(os.listdir(trial_dir)):
        if not fname.endswith(".log"):
            continue
        fpath = os.path.join(trial_dir, fname)
        with open(fpath) as f:
            for line in f:
                m = LINE_RE.match(line)
                if not m:
                    continue
                port = int(m.group(1))
                epoch_ms = int(m.group(2))
                body = m.group(3)
                ports.add(port)

                gm = GOSSIP_RECV_RE.search(body)
                if gm:
                    gossip_events.append((epoch_ms, port, gm.group(1), "recv"))

                gn = GOSSIP_NEW_RE.search(body)
                if gn:
                    gossip_events.append((epoch_ms, port, gn.group(1), "new"))

                st = SENT_RE.search(body)
                if st:
                    sent_events.append((epoch_ms, st.group(1)))

    return gossip_events, sent_events, len(ports)


def compute_metrics(trial_dir):
    """Compute convergence time and overhead for a single trial.

    Returns dict with keys: convergence_ms, overhead, n_nodes, delivery_ratio
    """
    events, sent_events, n_nodes = parse_trial(trial_dir)
    if not events or n_nodes == 0:
        return None

    # find the first GOSSIP message (the "new" event from the originator)
    new_events = [e for e in events if e[3] == "new"]
    if not new_events:
        return None
    msg_id = new_events[0][2]
    t0 = new_events[0][0]

    # gather receive times for this msg_id
    recv_times = {}
    for epoch_ms, port, mid, etype in events:
        if mid == msg_id and etype in ("recv", "new"):
            if port not in recv_times:
                recv_times[port] = epoch_ms

    delivery_count = len(recv_times)
    delivery_ratio = delivery_count / n_nodes

    # convergence time = time until 95% of nodes have the message
    target_count = int(n_nodes * 0.95)
    sorted_times = sorted(recv_times.values())

    if len(sorted_times) >= target_count:
        convergence_ms = sorted_times[target_count - 1] - t0
        t_converged = sorted_times[target_count - 1]
    else:
        convergence_ms = sorted_times[-1] - t0 if sorted_times else 0
        t_converged = sorted_times[-1] if sorted_times else t0

    # count only messages sent within the gossip window [t0, t_converged]
    sent_by_type = defaultdict(int)
    for epoch_ms, msg_type in sent_events:
        if t0 <= epoch_ms <= t_converged:
            sent_by_type[msg_type] += 1
    overhead = sum(sent_by_type.values())

    return {
        "convergence_ms": convergence_ms,
        "overhead": overhead,
        "n_nodes": n_nodes,
        "delivery_ratio": delivery_ratio,
        "delivery_count": delivery_count,
        "sent_by_type": dict(sent_by_type),
    }


# ---------------------------------------------------------------------------
# Discover and group trials
# ---------------------------------------------------------------------------

TRIAL_RE = re.compile(
    r"N(\d+)_seed(\d+)_fanout(\d+)_ttl(\d+)_(\w+)"
)


def load_all_trials():
    """Scan results/ and return a list of (params_dict, metrics_dict)."""
    if not os.path.isdir(RESULTS_DIR):
        print(f"No results directory found at {RESULTS_DIR}")
        sys.exit(1)

    trials = []
    for name in sorted(os.listdir(RESULTS_DIR)):
        m = TRIAL_RE.match(name)
        if not m:
            continue
        params = {
            "n": int(m.group(1)),
            "seed": int(m.group(2)),
            "fanout": int(m.group(3)),
            "ttl": int(m.group(4)),
            "mode": m.group(5),
        }
        trial_dir = os.path.join(RESULTS_DIR, name)
        metrics = compute_metrics(trial_dir)
        if metrics:
            trials.append((params, metrics))

    return trials


def group_by(trials, group_key, fixed=None):
    """Group trials by a parameter, optionally filtering by fixed params.

    Returns dict: group_value -> list of metrics dicts
    """
    groups = defaultdict(list)
    for params, metrics in trials:
        if fixed:
            skip = False
            for k, v in fixed.items():
                if params.get(k) != v:
                    skip = True
                    break
            if skip:
                continue
        groups[params[group_key]].append(metrics)
    return dict(groups)


def stats(values):
    """Return (mean, std) of a list of numbers."""
    a = np.array(values, dtype=float)
    return float(np.mean(a)), float(np.std(a))


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def plot_by_n(trials, mode="push"):
    """Chart: convergence time and overhead vs N."""
    groups = group_by(trials, "n", fixed={"mode": mode, "fanout": 3, "ttl": 8})
    if not groups:
        print(f"  no data for mode={mode}, fanout=3, ttl=8")
        return

    ns = sorted(groups.keys())
    conv_means, conv_stds = [], []
    over_means, over_stds = [], []

    for n in ns:
        convs = [m["convergence_ms"] for m in groups[n]]
        overs = [m["overhead"] for m in groups[n]]
        cm, cs = stats(convs)
        om, os_ = stats(overs)
        conv_means.append(cm)
        conv_stds.append(cs)
        over_means.append(om)
        over_stds.append(os_)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(f"Gossip Performance vs Network Size (mode={mode})")

    ax1.bar([str(n) for n in ns], conv_means, yerr=conv_stds, capsize=5,
            color="steelblue", alpha=0.8)
    ax1.set_xlabel("Number of Nodes (N)")
    ax1.set_ylabel("Convergence Time (ms)")
    ax1.set_title("95% Convergence Time")

    ax2.bar([str(n) for n in ns], over_means, yerr=over_stds, capsize=5,
            color="coral", alpha=0.8)
    ax2.set_xlabel("Number of Nodes (N)")
    ax2.set_ylabel("Total Messages Sent")
    ax2.set_title("Message Overhead")

    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, f"performance_vs_N_{mode}.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  saved {path}")


def plot_by_fanout(trials, mode="push"):
    """Chart: convergence and overhead vs fanout (for a fixed N)."""
    groups = group_by(trials, "fanout", fixed={"mode": mode, "ttl": 8})
    if not groups or len(groups) < 2:
        print("  not enough fanout variation data — skipping")
        return

    # group further by N
    by_n = defaultdict(lambda: defaultdict(list))
    for params, metrics in trials:
        if params["mode"] == mode and params["ttl"] == 8:
            by_n[params["n"]][params["fanout"]].append(metrics)

    for n, fanout_groups in sorted(by_n.items()):
        if len(fanout_groups) < 2:
            continue
        fanouts = sorted(fanout_groups.keys())
        conv_means = [stats([m["convergence_ms"] for m in fanout_groups[f]])[0]
                      for f in fanouts]
        over_means = [stats([m["overhead"] for m in fanout_groups[f]])[0]
                      for f in fanouts]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
        fig.suptitle(f"Effect of Fanout (N={n}, mode={mode})")

        ax1.plot(fanouts, conv_means, "o-", color="steelblue")
        ax1.set_xlabel("Fanout")
        ax1.set_ylabel("Convergence Time (ms)")
        ax1.set_title("95% Convergence Time")

        ax2.plot(fanouts, over_means, "o-", color="coral")
        ax2.set_xlabel("Fanout")
        ax2.set_ylabel("Total Messages Sent")
        ax2.set_title("Message Overhead")

        plt.tight_layout()
        path = os.path.join(CHARTS_DIR, f"fanout_effect_N{n}_{mode}.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"  saved {path}")


def plot_push_vs_hybrid(trials):
    """Chart: push-only vs hybrid comparison."""
    push_groups = group_by(trials, "n", fixed={"mode": "push", "fanout": 3, "ttl": 8})
    hybrid_groups = group_by(trials, "n", fixed={"mode": "hybrid", "fanout": 3, "ttl": 8})

    if not push_groups or not hybrid_groups:
        print("  need both push and hybrid data — skipping")
        return

    ns = sorted(set(push_groups.keys()) & set(hybrid_groups.keys()))
    if not ns:
        return

    push_conv = [stats([m["convergence_ms"] for m in push_groups[n]])[0] for n in ns]
    hybrid_conv = [stats([m["convergence_ms"] for m in hybrid_groups[n]])[0] for n in ns]
    push_over = [stats([m["overhead"] for m in push_groups[n]])[0] for n in ns]
    hybrid_over = [stats([m["overhead"] for m in hybrid_groups[n]])[0] for n in ns]

    x = np.arange(len(ns))
    w = 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Push-Only vs Hybrid Push-Pull")

    ax1.bar(x - w/2, push_conv, w, label="Push", color="steelblue", alpha=0.8)
    ax1.bar(x + w/2, hybrid_conv, w, label="Hybrid", color="seagreen", alpha=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([str(n) for n in ns])
    ax1.set_xlabel("N")
    ax1.set_ylabel("Convergence Time (ms)")
    ax1.legend()

    ax2.bar(x - w/2, push_over, w, label="Push", color="coral", alpha=0.8)
    ax2.bar(x + w/2, hybrid_over, w, label="Hybrid", color="seagreen", alpha=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels([str(n) for n in ns])
    ax2.set_xlabel("N")
    ax2.set_ylabel("Total Messages Sent")
    ax2.legend()

    plt.tight_layout()
    path = os.path.join(CHARTS_DIR, "push_vs_hybrid.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  saved {path}")


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(trials):
    """Print a summary table of all trial results."""
    print("\n" + "=" * 80)
    print(f"{'N':>4} {'seed':>5} {'fanout':>6} {'ttl':>4} {'mode':>7} "
          f"{'conv_ms':>8} {'overhead':>9} {'delivery':>9}")
    print("-" * 80)

    for params, metrics in sorted(trials, key=lambda t: (
            t[0]["mode"], t[0]["n"], t[0]["fanout"], t[0]["ttl"], t[0]["seed"])):
        print(f"{params['n']:>4} {params['seed']:>5} {params['fanout']:>6} "
              f"{params['ttl']:>4} {params['mode']:>7} "
              f"{metrics['convergence_ms']:>8.0f} {metrics['overhead']:>9} "
              f"{metrics['delivery_count']}/{metrics['n_nodes']}")

    print("=" * 80)

    # aggregate stats
    print("\nAggregated (mean ± std):")
    groups = defaultdict(list)
    for params, metrics in trials:
        key = (params["n"], params["fanout"], params["ttl"], params["mode"])
        groups[key].append(metrics)

    print(f"{'N':>4} {'fanout':>6} {'ttl':>4} {'mode':>7} "
          f"{'conv_ms':>16} {'overhead':>16} {'delivery':>10}")
    print("-" * 75)
    for key in sorted(groups.keys()):
        n, fanout, ttl, mode = key
        convs = [m["convergence_ms"] for m in groups[key]]
        overs = [m["overhead"] for m in groups[key]]
        delivs = [m["delivery_ratio"] for m in groups[key]]
        cm, cs = stats(convs)
        om, os_ = stats(overs)
        dm, ds = stats(delivs)
        print(f"{n:>4} {fanout:>6} {ttl:>4} {mode:>7} "
              f"{cm:>7.0f} ± {cs:<6.0f} {om:>7.0f} ± {os_:<6.0f} "
              f"{dm:>5.1%} ± {ds:.1%}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading trial results ...\n")
    trials = load_all_trials()
    if not trials:
        print("No trial data found. Run simulate.py first.")
        sys.exit(1)

    print(f"Found {len(trials)} trial(s).\n")

    os.makedirs(CHARTS_DIR, exist_ok=True)

    print("Generating charts:")
    plot_by_n(trials, mode="push")
    plot_by_n(trials, mode="hybrid")
    plot_by_fanout(trials, mode="push")
    plot_push_vs_hybrid(trials)

    print_summary(trials)
    print(f"\nCharts saved to {CHARTS_DIR}/")


if __name__ == "__main__":
    main()
