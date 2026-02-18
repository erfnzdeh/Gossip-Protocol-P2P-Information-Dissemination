"""Configuration for a Gossip protocol node."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GossipConfig:
    """All tuneable parameters for one Gossip node."""

    port: int = 8000
    bootstrap: Optional[str] = None  # "ip:port" of seed node, None if this IS the seed

    fanout: int = 3        # peers to forward each GOSSIP to
    ttl: int = 8           # max hops for a GOSSIP message
    peer_limit: int = 20   # max neighbours to keep
    ping_interval: float = 2.0   # seconds between PING rounds
    peer_timeout: float = 6.0    # seconds before a peer is considered dead

    seed: int = 42         # RNG seed for reproducibility

    # --- Phase 4 extensions (filled in later) ---
    mode: str = "push"             # "push" or "hybrid"
    pull_interval: float = 2.0     # seconds between IHAVE rounds (hybrid mode)
    ihave_max_ids: int = 32        # max msg_ids per IHAVE message
    pow_k: int = 0                 # PoW difficulty (0 = disabled)

    @property
    def self_addr(self) -> str:
        return f"127.0.0.1:{self.port}"
