"""GossipNode — the main actor in the Gossip protocol.

Owns the UDP socket, peer list, seen set, and all protocol logic.
Runs three concurrent asyncio tasks: listener, ping loop, user input loop.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

# Max entries kept in seen set / message store before oldest are evicted.
SEEN_SET_MAX = 10_000

from .config import GossipConfig
from .message import Message
from .pow import compute_pow, validate_pow

logger = logging.getLogger("gossip")


# ---------------------------------------------------------------------------
# Peer bookkeeping
# ---------------------------------------------------------------------------

@dataclass
class PeerInfo:
    node_id: str
    addr: str                       # "ip:port"
    last_seen: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# GossipNode
# ---------------------------------------------------------------------------

class GossipNode:
    """A single node in the Gossip network."""

    def __init__(self, config: GossipConfig):
        self.cfg = config
        self.node_id: str = uuid.uuid4().hex
        self.addr: str = config.self_addr
        self.rng = random.Random(config.seed)

        # state
        self.peers: dict[str, PeerInfo] = {}   # addr -> PeerInfo
        # Bounded ordered containers — oldest entries evicted when full.
        self.seen: collections.OrderedDict[str, bool] = collections.OrderedDict()
        self.message_store: collections.OrderedDict[str, Message] = collections.OrderedDict()

        # networking (set up in run())
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # log dir
        self._log_dir = os.path.join(os.getcwd(), "logs")

        # ping tracking
        self._pending_pings: dict[str, float] = {}  # ping_id -> send_time
        self._ping_seq: int = 0

        # PoW (computed in run() if pow_k > 0)
        self.pow_data: Optional[dict] = None

        # stats
        self.stats_sent: int = 0  # total messages sent

        # graceful shutdown
        self._running = False

    # -- public API -----------------------------------------------------------

    async def run(self):
        """Start the node and block until stopped."""
        self.loop = asyncio.get_running_loop()
        self._running = True
        self._setup_logging()

        # create UDP endpoint
        self.transport, _ = await self.loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self),
            local_addr=("127.0.0.1", self.cfg.port),
        )

        logger.info("node started  id=%s  addr=%s", self.node_id, self.addr)

        # compute PoW if enabled
        if self.cfg.pow_k > 0:
            logger.info("computing PoW  k=%d ...", self.cfg.pow_k)
            self.pow_data = compute_pow(self.node_id, self.cfg.pow_k)
            logger.info("PoW found  nonce=%d  digest=%s  elapsed=%.1fms",
                        self.pow_data["nonce"],
                        self.pow_data["digest_hex"][:16],
                        self.pow_data["elapsed_ms"])

        # bootstrap
        if self.cfg.bootstrap:
            await self._bootstrap()

        # run concurrent tasks
        tasks = [
            asyncio.create_task(self._ping_loop()),
            asyncio.create_task(self._input_loop()),
        ]
        if self.cfg.mode == "hybrid":
            tasks.append(asyncio.create_task(self._pull_loop()))
            logger.info("hybrid mode enabled  pull_interval=%s  ihave_max_ids=%d",
                        self.cfg.pull_interval, self.cfg.ihave_max_ids)

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.transport.close()
            logger.info("STATS sent=%d peers=%d seen=%d",
                        self.stats_sent, len(self.peers), len(self.seen))
            logger.info("node stopped")

    def stop(self):
        self._running = False
        for task in asyncio.all_tasks(self.loop):
            task.cancel()

    # -- bootstrap ------------------------------------------------------------

    async def _bootstrap(self):
        """Join the network via the seed node."""
        seed_addr = self.cfg.bootstrap
        logger.info("bootstrap  -> %s", seed_addr)

        # send HELLO (with PoW if enabled)
        hello = Message.hello(self.node_id, self.addr, pow_data=self.pow_data)
        self._send_to_addr(hello, seed_addr)

        # send GET_PEERS
        gp = Message.get_peers(self.node_id, self.addr,
                               max_peers=self.cfg.peer_limit)
        self._send_to_addr(gp, seed_addr)

    # -- message dispatch -----------------------------------------------------

    def _on_datagram(self, data: bytes, addr: tuple[str, int]):
        """Called by the UDP protocol when a packet arrives."""
        msg = Message.from_bytes(data)
        if msg is None:
            logger.warning("bad packet from %s:%d", *addr)
            return

        handler = {
            "HELLO": self._handle_hello,
            "GET_PEERS": self._handle_get_peers,
            "PEERS_LIST": self._handle_peers_list,
            "GOSSIP": self._handle_gossip,
            "PING": self._handle_ping,
            "PONG": self._handle_pong,
            "IHAVE": self._handle_ihave,
            "IWANT": self._handle_iwant,
        }.get(msg.msg_type)

        if handler:
            handler(msg)

    # -- handlers -------------------------------------------------------------

    def _handle_hello(self, msg: Message):
        logger.info("HELLO from %s (%s)", msg.sender_addr, msg.sender_id[:8])

        # validate PoW if required
        if self.cfg.pow_k > 0:
            pow_data = msg.payload.get("pow")
            if not validate_pow(msg.sender_id, pow_data, self.cfg.pow_k):
                logger.warning("HELLO rejected: invalid PoW from %s",
                               msg.sender_addr)
                return

        self._add_peer(msg.sender_id, msg.sender_addr)

        # reply with our peer list so the newcomer can discover the network
        self._send_peers_list(msg.sender_addr)

    def _handle_get_peers(self, msg: Message):
        max_peers = msg.payload.get("max_peers", 20)
        logger.info("GET_PEERS from %s (max=%d)", msg.sender_addr, max_peers)

        # only add sender as peer if PoW not required or already known
        if self.cfg.pow_k > 0 and msg.sender_addr not in self.peers:
            logger.warning("GET_PEERS ignored: %s not authenticated (no HELLO with PoW)",
                           msg.sender_addr)
            return

        self._add_peer(msg.sender_id, msg.sender_addr)
        self._send_peers_list(msg.sender_addr, max_peers)

    def _handle_peers_list(self, msg: Message):
        peers = msg.payload.get("peers", [])
        logger.info("PEERS_LIST from %s  (%d peers)", msg.sender_addr, len(peers))
        self._add_peer(msg.sender_id, msg.sender_addr)
        for p in peers:
            pid = p.get("node_id", "")
            paddr = p.get("addr", "")
            if paddr and paddr != self.addr:
                self._add_peer(pid, paddr)

    def _handle_gossip(self, msg: Message):
        if msg.msg_id in self.seen:
            return  # duplicate

        self._mark_seen(msg.msg_id, msg)

        data_preview = str(msg.payload.get("data", ""))[:40]
        logger.info("GOSSIP recv  msg_id=%s  data=%s  ttl=%d",
                     msg.msg_id[:8], data_preview, msg.ttl)

        # add sender as peer
        self._add_peer(msg.sender_id, msg.sender_addr)

        # forward if TTL allows
        new_ttl = msg.ttl - 1
        if new_ttl <= 0:
            return

        self._forward_gossip(msg, new_ttl)

    def _handle_ping(self, msg: Message):
        self._add_peer(msg.sender_id, msg.sender_addr)
        ping_id = msg.payload.get("ping_id", "")
        seq = msg.payload.get("seq", 0)
        pong = Message.pong(self.node_id, self.addr, ping_id=ping_id, seq=seq)
        self._send_to_addr(pong, msg.sender_addr)

    def _handle_pong(self, msg: Message):
        ping_id = msg.payload.get("ping_id", "")
        if ping_id in self._pending_pings:
            rtt_ms = (time.time() - self._pending_pings.pop(ping_id)) * 1000
            logger.debug("PONG from %s  rtt=%.1fms", msg.sender_addr, rtt_ms)
        self._add_peer(msg.sender_id, msg.sender_addr)

    def _handle_ihave(self, msg: Message):
        """Hybrid pull: peer announces msg_ids it has."""
        ids = msg.payload.get("ids", [])
        self._add_peer(msg.sender_id, msg.sender_addr)
        missing = [mid for mid in ids if mid not in self.seen]
        if missing:
            iwant = Message.iwant(self.node_id, self.addr, missing)
            self._send_to_addr(iwant, msg.sender_addr)

    def _handle_iwant(self, msg: Message):
        """Hybrid pull: peer requests full messages by id."""
        ids = msg.payload.get("ids", [])
        self._add_peer(msg.sender_id, msg.sender_addr)
        for mid in ids:
            stored = self.message_store.get(mid)
            if stored:
                fwd = Message.gossip(
                    self.node_id, self.addr,
                    data=stored.payload.get("data", ""),
                    origin_id=stored.payload.get("origin_id", ""),
                    ttl=1,  # direct delivery, no further forwarding
                    topic=stored.payload.get("topic", "news"),
                    origin_timestamp_ms=stored.payload.get("origin_timestamp_ms"),
                    msg_id=stored.msg_id,
                )
                self._send_to_addr(fwd, msg.sender_addr)

    # -- seen-set management --------------------------------------------------

    def _mark_seen(self, msg_id: str, msg: Message | None = None):
        """Record a msg_id as seen.  Stores the full message if provided.

        Evicts the oldest entries when the bounded capacity is reached.
        """
        self.seen[msg_id] = True
        if msg is not None:
            self.message_store[msg_id] = msg
        # evict oldest if over capacity
        while len(self.seen) > SEEN_SET_MAX:
            oldest_id, _ = self.seen.popitem(last=False)
            self.message_store.pop(oldest_id, None)

    # -- gossip forwarding ----------------------------------------------------

    def _forward_gossip(self, original: Message, new_ttl: int):
        """Forward a gossip message to `fanout` random peers."""
        candidates = [a for a in self.peers if a != original.sender_addr]
        k = min(self.cfg.fanout, len(candidates))
        if k == 0:
            return
        targets = self.rng.sample(candidates, k)
        for target_addr in targets:
            fwd = Message.gossip(
                self.node_id, self.addr,
                data=original.payload.get("data", ""),
                origin_id=original.payload.get("origin_id", self.node_id),
                ttl=new_ttl,
                topic=original.payload.get("topic", "news"),
                origin_timestamp_ms=original.payload.get("origin_timestamp_ms"),
                msg_id=original.msg_id,
            )
            self._send_to_addr(fwd, target_addr)
            logger.info("GOSSIP fwd   msg_id=%s -> %s  ttl=%d",
                         original.msg_id[:8], target_addr, new_ttl)

    # -- peer management ------------------------------------------------------

    def _add_peer(self, node_id: str, addr: str):
        """Add or update a peer.  Evicts least-recently-seen if at capacity."""
        if addr == self.addr:
            return
        if addr in self.peers:
            self.peers[addr].last_seen = time.time()
            if node_id:
                self.peers[addr].node_id = node_id
            return
        if len(self.peers) >= self.cfg.peer_limit:
            self._evict_oldest_peer()
        self.peers[addr] = PeerInfo(node_id=node_id, addr=addr)
        logger.info("peer added   %s (%s)", addr, node_id[:8] if node_id else "?")

    def _evict_oldest_peer(self):
        if not self.peers:
            return
        oldest_addr = min(self.peers, key=lambda a: self.peers[a].last_seen)
        logger.info("peer evicted %s", oldest_addr)
        del self.peers[oldest_addr]

    def _remove_peer(self, addr: str):
        if addr in self.peers:
            logger.info("peer removed %s (timeout)", addr)
            del self.peers[addr]

    def _send_peers_list(self, target_addr: str, max_peers: int = 20):
        entries = [
            {"node_id": p.node_id, "addr": p.addr}
            for p in list(self.peers.values())[:max_peers]
        ]
        reply = Message.peers_list(self.node_id, self.addr, entries)
        self._send_to_addr(reply, target_addr)

    # -- periodic loops -------------------------------------------------------

    async def _ping_loop(self):
        """Periodically ping peers and remove dead ones."""
        while self._running:
            await asyncio.sleep(self.cfg.ping_interval)
            if not self.peers:
                continue

            now = time.time()

            # remove peers that haven't been seen within timeout
            dead = [addr for addr, p in self.peers.items()
                    if now - p.last_seen > self.cfg.peer_timeout]
            for addr in dead:
                self._remove_peer(addr)

            # clean up stale pending pings (no PONG received in time)
            stale_pings = [pid for pid, t in self._pending_pings.items()
                           if now - t > self.cfg.peer_timeout]
            for pid in stale_pings:
                del self._pending_pings[pid]

            # send PINGs to a subset of remaining peers
            if self.peers:
                k = min(self.cfg.fanout, len(self.peers))
                targets = self.rng.sample(list(self.peers.keys()), k)
                for addr in targets:
                    self._ping_seq += 1
                    ping = Message.ping(self.node_id, self.addr,
                                        seq=self._ping_seq)
                    self._pending_pings[ping.payload["ping_id"]] = now
                    self._send_to_addr(ping, addr)

    async def _pull_loop(self):
        """Hybrid mode: periodically send IHAVE to peers so they can request missing msgs."""
        while self._running:
            await asyncio.sleep(self.cfg.pull_interval)
            if not self.peers or not self.seen:
                continue

            # pick most recent msg_ids to announce (OrderedDict keeps insertion order)
            recent_ids = list(self.seen.keys())[-self.cfg.ihave_max_ids:]

            # send to fanout peers
            k = min(self.cfg.fanout, len(self.peers))
            targets = self.rng.sample(list(self.peers.keys()), k)
            ihave_msg = Message.ihave(self.node_id, self.addr, recent_ids,
                                      max_ids=self.cfg.ihave_max_ids)
            for addr in targets:
                self._send_to_addr(ihave_msg, addr)

    async def _input_loop(self):
        """Read lines from stdin and broadcast as GOSSIP messages."""
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, self._read_stdin)
            except EOFError:
                # stdin closed (running as subprocess) — just keep the node alive
                await asyncio.sleep(3600)
                continue
            if line is None:
                continue
            line = line.strip()
            if not line:
                continue
            self._broadcast_gossip(line)

    def _read_stdin(self) -> Optional[str]:
        """Blocking stdin read, run in executor."""
        import sys
        try:
            return sys.stdin.readline()
        except Exception:
            return None

    def _broadcast_gossip(self, data: str):
        """Create a new GOSSIP message and send to fanout peers."""
        msg = Message.gossip(self.node_id, self.addr,
                             data=data, origin_id=self.node_id,
                             ttl=self.cfg.ttl)
        self._mark_seen(msg.msg_id, msg)
        logger.info("GOSSIP new   msg_id=%s  data=%s", msg.msg_id[:8], data[:40])

        candidates = list(self.peers.keys())
        k = min(self.cfg.fanout, len(candidates))
        if k == 0:
            logger.warning("no peers to gossip to")
            return
        targets = self.rng.sample(candidates, k)
        for addr in targets:
            fwd = Message.gossip(
                self.node_id, self.addr,
                data=data, origin_id=self.node_id,
                ttl=self.cfg.ttl,
                msg_id=msg.msg_id,
                origin_timestamp_ms=msg.payload["origin_timestamp_ms"],
            )
            self._send_to_addr(fwd, addr)

    # -- transport helpers ----------------------------------------------------

    def _send_to_addr(self, msg: Message, addr: str):
        """Send a message to an ip:port string."""
        if self.transport is None:
            return
        try:
            host, port_s = addr.rsplit(":", 1)
            self.transport.sendto(msg.to_bytes(), (host, int(port_s)))
            self.stats_sent += 1
            logger.debug("SENT %s -> %s", msg.msg_type, addr)
        except Exception as exc:
            logger.warning("send failed -> %s: %s", addr, exc)

    # -- logging setup --------------------------------------------------------

    def _setup_logging(self):
        os.makedirs(self._log_dir, exist_ok=True)
        log_file = os.path.join(self._log_dir, f"node_{self.cfg.port}.log")

        # Include epoch_ms in each line for analysis scripts
        class _EpochFormatter(logging.Formatter):
            def __init__(self, port):
                super().__init__()
                self.port = port

            def format(self, record):
                epoch_ms = int(record.created * 1000)
                ts = time.strftime("%H:%M:%S", time.localtime(record.created))
                ms = int(record.created * 1000) % 1000
                return f"{ts}.{ms:03d} [{self.port}] [{epoch_ms}] {record.getMessage()}"

        formatter = _EpochFormatter(self.cfg.port)

        # file handler
        fh = logging.FileHandler(log_file, mode="w")
        fh.setFormatter(formatter)
        fh.setLevel(logging.DEBUG)

        # console handler (less verbose)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        ch.setLevel(logging.INFO)

        root = logging.getLogger("gossip")
        root.setLevel(logging.DEBUG)
        # avoid duplicate handlers on re-runs
        root.handlers.clear()
        root.addHandler(fh)
        root.addHandler(ch)


# ---------------------------------------------------------------------------
# asyncio UDP protocol adapter
# ---------------------------------------------------------------------------

class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, node: GossipNode):
        self.node = node

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        self.node._on_datagram(data, addr)

    def error_received(self, exc: Exception):
        logger.warning("UDP error: %s", exc)
