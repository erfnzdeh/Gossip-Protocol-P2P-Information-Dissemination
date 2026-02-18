"""Message definitions for the Gossip protocol (JSON over UDP)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


# All recognised message types
MSG_TYPES = {"HELLO", "GET_PEERS", "PEERS_LIST", "GOSSIP", "PING", "PONG",
             "IHAVE", "IWANT"}


@dataclass
class Message:
    """One protocol message, serialisable to/from JSON bytes."""

    msg_type: str
    sender_id: str
    sender_addr: str
    payload: dict[str, Any] = field(default_factory=dict)
    ttl: int = 8
    version: int = 1
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    # -- serialisation --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "msg_id": self.msg_id,
            "msg_type": self.msg_type,
            "sender_id": self.sender_id,
            "sender_addr": self.sender_addr,
            "timestamp_ms": self.timestamp_ms,
            "ttl": self.ttl,
            "payload": self.payload,
        }

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_dict()).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["Message"]:
        """Deserialise bytes into a Message.  Returns None on any error."""
        try:
            d = json.loads(data.decode("utf-8"))
            if not isinstance(d, dict):
                return None
            msg_type = d.get("msg_type", "")
            if msg_type not in MSG_TYPES:
                return None
            return cls(
                version=d.get("version", 1),
                msg_id=d.get("msg_id", uuid.uuid4().hex),
                msg_type=msg_type,
                sender_id=d.get("sender_id", ""),
                sender_addr=d.get("sender_addr", ""),
                timestamp_ms=d.get("timestamp_ms", 0),
                ttl=d.get("ttl", 0),
                payload=d.get("payload", {}),
            )
        except Exception:
            return None

    # -- factory helpers ------------------------------------------------------

    @classmethod
    def hello(cls, sender_id: str, sender_addr: str, *,
              pow_data: Optional[dict] = None) -> "Message":
        payload: dict[str, Any] = {"capabilities": ["udp", "json"]}
        if pow_data is not None:
            payload["pow"] = pow_data
        return cls(msg_type="HELLO", sender_id=sender_id,
                   sender_addr=sender_addr, payload=payload)

    @classmethod
    def get_peers(cls, sender_id: str, sender_addr: str, *,
                  max_peers: int = 20) -> "Message":
        return cls(msg_type="GET_PEERS", sender_id=sender_id,
                   sender_addr=sender_addr,
                   payload={"max_peers": max_peers})

    @classmethod
    def peers_list(cls, sender_id: str, sender_addr: str,
                   peers: list[dict[str, str]]) -> "Message":
        return cls(msg_type="PEERS_LIST", sender_id=sender_id,
                   sender_addr=sender_addr, payload={"peers": peers})

    @classmethod
    def gossip(cls, sender_id: str, sender_addr: str,
               data: str, origin_id: str, ttl: int, *,
               topic: str = "news",
               origin_timestamp_ms: Optional[int] = None,
               msg_id: Optional[str] = None) -> "Message":
        return cls(
            msg_type="GOSSIP",
            sender_id=sender_id,
            sender_addr=sender_addr,
            ttl=ttl,
            msg_id=msg_id or uuid.uuid4().hex,
            payload={
                "topic": topic,
                "data": data,
                "origin_id": origin_id,
                "origin_timestamp_ms": origin_timestamp_ms or int(time.time() * 1000),
            },
        )

    @classmethod
    def ping(cls, sender_id: str, sender_addr: str, *,
             seq: int = 0) -> "Message":
        return cls(msg_type="PING", sender_id=sender_id,
                   sender_addr=sender_addr,
                   payload={"ping_id": uuid.uuid4().hex, "seq": seq})

    @classmethod
    def pong(cls, sender_id: str, sender_addr: str, *,
             ping_id: str, seq: int = 0) -> "Message":
        return cls(msg_type="PONG", sender_id=sender_id,
                   sender_addr=sender_addr,
                   payload={"ping_id": ping_id, "seq": seq})

    @classmethod
    def ihave(cls, sender_id: str, sender_addr: str,
              ids: list[str], *, max_ids: int = 32) -> "Message":
        return cls(msg_type="IHAVE", sender_id=sender_id,
                   sender_addr=sender_addr,
                   payload={"ids": ids[:max_ids], "max_ids": max_ids})

    @classmethod
    def iwant(cls, sender_id: str, sender_addr: str,
              ids: list[str]) -> "Message":
        return cls(msg_type="IWANT", sender_id=sender_id,
                   sender_addr=sender_addr,
                   payload={"ids": ids})
