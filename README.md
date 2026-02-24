# Gossip Protocol — P2P Information Dissemination

A Python implementation of a Gossip protocol for peer-to-peer information dissemination over UDP, built for the Computer Networks course (40443).

## Quick Start

```bash
# create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# start a seed node
python -m gossip --port 9000

# in another terminal, join with a new node
python -m gossip --port 9001 --bootstrap 127.0.0.1:9000

# type a message in any node's terminal to broadcast it
```

## Architecture

```
gossip/
    __init__.py
    __main__.py     # CLI entry point (argparse)
    config.py       # GossipConfig dataclass
    message.py      # Message dataclass + JSON serialisation
    node.py         # GossipNode — UDP transport, peers, gossip, ping
    pow.py          # Proof-of-Work (SHA-256) for Sybil resistance
tests/
    test_messages.py    # Message serialisation round-trips
    test_bootstrap.py   # 3-node bootstrap test
    test_gossip_10.py   # 10-node gossip delivery test
    test_hybrid.py      # Push vs Hybrid comparison
    test_pow.py         # PoW computation, validation, timing
scripts/
    simulate.py         # Automated simulation runner
    analyze.py          # Log parser + chart generator
```

Each node runs three concurrent asyncio tasks:
1. **Listener** — UDP socket receiving messages, dispatching to handlers
2. **Ping loop** — periodic PING/PONG for peer liveness detection
3. **Input loop** — reads stdin to create new GOSSIP messages

In hybrid mode, a fourth **Pull loop** sends periodic IHAVE messages.

## CLI Parameters

```
python -m gossip [OPTIONS]

--port              Port to listen on (default: 8000)
--bootstrap         ip:port of seed node (omit for seed node itself)
--fanout            Peers to forward each GOSSIP to (default: 3)
--ttl               Max hops for GOSSIP messages (default: 8)
--peer-limit        Max neighbours to keep (default: 20)
--ping-interval     Seconds between PING rounds (default: 2.0)
--peer-timeout      Seconds before peer considered dead (default: 6.0)
--seed              RNG seed for reproducibility (default: 42)
--mode              "push" or "hybrid" (default: push)
--pull-interval     Seconds between IHAVE rounds in hybrid mode (default: 2.0)
--ihave-max-ids     Max msg_ids per IHAVE message (default: 32)
--pow-k             PoW difficulty — leading hex zeros required (default: 0 = off)
```

## Message Types

All messages are JSON over UDP with a common header:

| Field | Description |
|-------|-------------|
| `version` | Protocol version (1) |
| `msg_id` | Unique message identifier (UUID hex) |
| `msg_type` | HELLO, GET_PEERS, PEERS_LIST, GOSSIP, PING, PONG, IHAVE, IWANT |
| `sender_id` | Node UUID |
| `sender_addr` | "ip:port" of sender |
| `timestamp_ms` | Epoch milliseconds |
| `ttl` | Time-to-live (hops remaining) |
| `payload` | Type-specific data |

## Running Tests

```bash
# Phase 1: message serialisation
python tests/test_messages.py

# Phase 2: bootstrap (3 nodes) + gossip delivery (10 nodes)
python tests/test_bootstrap.py
python tests/test_gossip_10.py

# Phase 4: hybrid push-pull + PoW
python tests/test_hybrid.py
python tests/test_pow.py
```

## Running Simulations

```bash
# activate venv first
source .venv/bin/activate

# full simulation: N={10,20,50} x 5 seeds, push mode
python scripts/simulate.py

# vary fanout
python scripts/simulate.py --sizes 10 20 50 --seeds 3 --fanouts 2 3 5

# hybrid mode
python scripts/simulate.py --sizes 10 20 50 --seeds 5 --mode hybrid

# quick test
python scripts/simulate.py --sizes 10 --seeds 1

# generate charts from results
python scripts/analyze.py
```

Charts are saved to `charts/`. Results data is in `results/`.

## Performance Results (Summary)

| N | Fanout | Mode | Convergence (ms) | Overhead (msgs) | Delivery |
|---|--------|------|-------------------|-----------------|----------|
| 10 | 3 | push | 1 ± 0 | 563 ± 1 | 98% ± 4% |
| 10 | 3 | hybrid | 2 ± 1 | 624 ± 0 | 100% ± 0% |
| 20 | 3 | push | 2 ± 1 | 1495 ± 3 | 95% ± 6% |
| 20 | 3 | hybrid | 115 ± 140 | 1616 ± 22 | 100% ± 0% |
| 50 | 3 | push | 9 ± 1 | 6364 ± 4 | 98% ± 2% |
| 50 | 3 | hybrid | 8 ± 4 | 6934 ± 35 | 100% ± 0% |

### PoW Timing (SHA-256, Apple M-series)

| k (hex zeros) | Mean time | Range |
|---------------|-----------|-------|
| 2 | ~0.1 ms | 0 - 0.1 ms |
| 3 | ~1 ms | 0.8 - 2 ms |
| 4 | ~50 ms | 8 - 90 ms |
| 5 | ~560 ms | 70 - 1060 ms |

## License

Course project — Computer Networks 40443.
