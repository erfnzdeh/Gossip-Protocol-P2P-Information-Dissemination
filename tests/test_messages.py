#!/usr/bin/env python3
"""Phase 1 tests: message creation, serialisation round-trips, edge cases."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gossip.message import Message, MSG_TYPES
from gossip.config import GossipConfig

PASS = 0
FAIL = 0

def check(name: str, condition: bool):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def test_config_defaults():
    print("\n--- GossipConfig defaults ---")
    cfg = GossipConfig()
    check("default port", cfg.port == 8000)
    check("default fanout", cfg.fanout == 3)
    check("default ttl", cfg.ttl == 8)
    check("self_addr", cfg.self_addr == "127.0.0.1:8000")
    check("bootstrap is None", cfg.bootstrap is None)


def test_config_custom():
    print("\n--- GossipConfig custom ---")
    cfg = GossipConfig(port=9000, bootstrap="127.0.0.1:8000", fanout=5,
                       ttl=10, peer_limit=30, seed=99)
    check("custom port", cfg.port == 9000)
    check("custom bootstrap", cfg.bootstrap == "127.0.0.1:8000")
    check("custom fanout", cfg.fanout == 5)
    check("custom self_addr", cfg.self_addr == "127.0.0.1:9000")


def test_hello_roundtrip():
    print("\n--- HELLO round-trip ---")
    msg = Message.hello("node-1", "127.0.0.1:8000")
    check("msg_type", msg.msg_type == "HELLO")
    check("has capabilities", "capabilities" in msg.payload)
    data = msg.to_bytes()
    restored = Message.from_bytes(data)
    check("from_bytes succeeds", restored is not None)
    check("msg_id preserved", restored.msg_id == msg.msg_id)
    check("msg_type preserved", restored.msg_type == "HELLO")
    check("sender_id preserved", restored.sender_id == "node-1")
    check("payload preserved", restored.payload == msg.payload)


def test_get_peers_roundtrip():
    print("\n--- GET_PEERS round-trip ---")
    msg = Message.get_peers("node-1", "127.0.0.1:8000", max_peers=15)
    data = msg.to_bytes()
    restored = Message.from_bytes(data)
    check("from_bytes succeeds", restored is not None)
    check("max_peers preserved", restored.payload["max_peers"] == 15)


def test_peers_list_roundtrip():
    print("\n--- PEERS_LIST round-trip ---")
    peers = [
        {"node_id": "node-2", "addr": "127.0.0.1:8001"},
        {"node_id": "node-3", "addr": "127.0.0.1:8002"},
    ]
    msg = Message.peers_list("node-1", "127.0.0.1:8000", peers)
    data = msg.to_bytes()
    restored = Message.from_bytes(data)
    check("from_bytes succeeds", restored is not None)
    check("peers count", len(restored.payload["peers"]) == 2)
    check("first peer addr", restored.payload["peers"][0]["addr"] == "127.0.0.1:8001")


def test_gossip_roundtrip():
    print("\n--- GOSSIP round-trip ---")
    msg = Message.gossip("node-1", "127.0.0.1:8000",
                         data="Hello network!", origin_id="node-1", ttl=8)
    data = msg.to_bytes()
    restored = Message.from_bytes(data)
    check("from_bytes succeeds", restored is not None)
    check("data preserved", restored.payload["data"] == "Hello network!")
    check("origin_id preserved", restored.payload["origin_id"] == "node-1")
    check("ttl preserved", restored.ttl == 8)


def test_ping_pong_roundtrip():
    print("\n--- PING/PONG round-trip ---")
    ping = Message.ping("node-1", "127.0.0.1:8000", seq=17)
    data = ping.to_bytes()
    restored = Message.from_bytes(data)
    check("ping from_bytes", restored is not None)
    check("ping seq", restored.payload["seq"] == 17)
    ping_id = restored.payload["ping_id"]

    pong = Message.pong("node-2", "127.0.0.1:8001", ping_id=ping_id, seq=17)
    data2 = pong.to_bytes()
    restored2 = Message.from_bytes(data2)
    check("pong from_bytes", restored2 is not None)
    check("pong ping_id matches", restored2.payload["ping_id"] == ping_id)
    check("pong seq", restored2.payload["seq"] == 17)


def test_ihave_iwant_roundtrip():
    print("\n--- IHAVE / IWANT round-trip ---")
    ihave = Message.ihave("node-1", "127.0.0.1:8000", ["id1", "id2", "id3"])
    data = ihave.to_bytes()
    restored = Message.from_bytes(data)
    check("ihave from_bytes", restored is not None)
    check("ihave ids count", len(restored.payload["ids"]) == 3)

    iwant = Message.iwant("node-2", "127.0.0.1:8001", ["id2", "id3"])
    data2 = iwant.to_bytes()
    restored2 = Message.from_bytes(data2)
    check("iwant from_bytes", restored2 is not None)
    check("iwant ids count", len(restored2.payload["ids"]) == 2)


def test_invalid_data():
    print("\n--- Invalid data handling ---")
    check("garbage bytes", Message.from_bytes(b"not json at all") is None)
    check("empty bytes", Message.from_bytes(b"") is None)
    check("valid json but array", Message.from_bytes(b"[1,2,3]") is None)
    check("valid json but bad type",
          Message.from_bytes(b'{"msg_type":"UNKNOWN"}') is None)

    # valid JSON but missing fields -> should still parse with defaults
    minimal = b'{"msg_type":"PING","sender_id":"x","sender_addr":"y"}'
    restored = Message.from_bytes(minimal)
    check("minimal PING parses", restored is not None)
    check("minimal PING type", restored.msg_type == "PING")


def test_all_msg_types_covered():
    print("\n--- All message types have factories ---")
    factories = {
        "HELLO": Message.hello("n", "a"),
        "GET_PEERS": Message.get_peers("n", "a"),
        "PEERS_LIST": Message.peers_list("n", "a", []),
        "GOSSIP": Message.gossip("n", "a", "d", "n", 8),
        "PING": Message.ping("n", "a"),
        "PONG": Message.pong("n", "a", ping_id="x"),
        "IHAVE": Message.ihave("n", "a", []),
        "IWANT": Message.iwant("n", "a", []),
    }
    for mtype, msg in factories.items():
        check(f"factory {mtype}", msg.msg_type == mtype)
    check("all types covered", set(factories.keys()) == MSG_TYPES)


if __name__ == "__main__":
    test_config_defaults()
    test_config_custom()
    test_hello_roundtrip()
    test_get_peers_roundtrip()
    test_peers_list_roundtrip()
    test_gossip_roundtrip()
    test_ping_pong_roundtrip()
    test_ihave_iwant_roundtrip()
    test_invalid_data()
    test_all_msg_types_covered()

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        sys.exit(1)
    else:
        print("All tests passed!")
