"""CLI entry point:  python -m gossip --port 8000 --bootstrap 127.0.0.1:9000 ..."""

import argparse
import asyncio
import sys

from .config import GossipConfig
from .node import GossipNode


def parse_args(argv=None) -> GossipConfig:
    p = argparse.ArgumentParser(description="Gossip protocol node")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--bootstrap", type=str, default=None,
                   help="ip:port of seed node")
    p.add_argument("--fanout", type=int, default=3)
    p.add_argument("--ttl", type=int, default=8)
    p.add_argument("--peer-limit", type=int, default=20)
    p.add_argument("--ping-interval", type=float, default=2.0)
    p.add_argument("--peer-timeout", type=float, default=6.0)
    p.add_argument("--seed", type=int, default=42)
    # phase 4 extensions
    p.add_argument("--mode", choices=["push", "hybrid"], default="push")
    p.add_argument("--pull-interval", type=float, default=2.0)
    p.add_argument("--ihave-max-ids", type=int, default=32)
    p.add_argument("--pow-k", type=int, default=0)

    args = p.parse_args(argv)
    return GossipConfig(
        port=args.port,
        bootstrap=args.bootstrap,
        fanout=args.fanout,
        ttl=args.ttl,
        peer_limit=args.peer_limit,
        ping_interval=args.ping_interval,
        peer_timeout=args.peer_timeout,
        seed=args.seed,
        mode=args.mode,
        pull_interval=args.pull_interval,
        ihave_max_ids=args.ihave_max_ids,
        pow_k=args.pow_k,
    )


def main():
    config = parse_args()
    node = GossipNode(config)
    try:
        asyncio.run(node.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
