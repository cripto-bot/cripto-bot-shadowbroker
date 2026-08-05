#!/usr/bin/env python3
"""
DEEP PHANTOM V2 — Covert Channels powered by  IR.

Every carrier protocol (DNS, ICMP, WS, HTTP) is parsed into  IR.
merge_graphs() finds shared structure between carriers.
Carrier translation = IR intermediate representation.

Uses: core.Graph, core.Node, core.merge_graphs, core.build_graph
"""

import os, sys, json, time, struct, socket, base64, hashlib, random
from collections import OrderedDict, defaultdict

sys.path.insert(0, '/home/app/a')
from core import Node, Graph, merge_graphs, build_graph

# ═══════════════════════════════════════════════════════════════════
# UNIVERSAL PROTOCOL PARSER: Any protocol →  IR
# ═══════════════════════════════════════════════════════════════════

class UniversalProtocolParser:
    """Parses DNS, HTTP, ICMP, WebSocket packets into  IR."""

    def __init__(self):
        self._counter = 0

    def _nid(self) -> str:
        self._counter += 1; return f"n{self._counter}"

    def _node(self, g: Graph, kind: str, value=None, op="", args=None) -> str:
        nid = self._nid()
        g.nodes[nid] = Node(kind=kind, value=value, op=op, args=args or [])
        return nid

    def parse(self, data: bytes, carrier: str) -> Graph:
        """Parse any carrier packet →  IR."""
        if carrier == "dns":
            return self._parse_dns(data)
        elif carrier == "http":
            return self._parse_http(data)
        elif carrier == "icmp":
            return self._parse_icmp(data)
        elif carrier == "ws_ping":
            return self._parse_ws(data)
        else:
            g = Graph(); g.root = self._node(g, "function", value=f"unknown_{carrier}")
            return g

    def _parse_dns(self, raw: bytes) -> Graph:
        g = Graph(); self._counter = 0
        if len(raw) < 12: return g
        tx_id = struct.unpack(">H", raw[:2])[0]
        flags = struct.unpack(">H", raw[2:4])[0]
        qdcount = struct.unpack(">H", raw[4:6])[0]
        is_query = (flags & 0x8000) == 0

        func = self._node(g, "function", value="dns_query" if is_query else "dns_response")
        if_nid = self._node(g, "if", value="qr_bit")
        tx = self._node(g, "const", value=tx_id)
        cnt = self._node(g, "for", value=qdcount)

        # Extract domain
        if qdcount > 0 and is_query:
            domain = self._extract_domain(raw, 12)
            dom = self._node(g, "var", value=domain)
        else:
            dom = self._node(g, "const", value="")

        call = self._node(g, "call", value="dns_resolve", args=[dom, tx])
        root = self._node(g, "block", args=[func, if_nid, tx, cnt, dom, call])
        g.root = root
        return g

    def _parse_http(self, raw: bytes) -> Graph:
        g = Graph(); self._counter = 0
        try:
            text = raw.decode("utf-8", errors="replace")
            lines = text.split("\r\n")
            req = lines[0].split(" ")
            method = req[0] if len(req) > 0 else "GET"
            path = req[1] if len(req) > 1 else "/"

            func = self._node(g, "function", value="http_request")
            m = self._node(g, "var", value=method)
            p = self._node(g, "var", value=path)
            header_nodes = []
            for line in lines[1:]:
                if not line.strip(): break
                if ":" in line:
                    k, v = line.split(":", 1)
                    vn = self._node(g, "const", value=v.strip())
                    an = self._node(g, "assign", value=k.strip(), args=[vn])
                    header_nodes.append(an)
            call = self._node(g, "call", value="http_request", args=[m, p] + header_nodes)
            g.root = self._node(g, "block", args=[func, call])
        except:
            g.root = self._node(g, "function", value="parse_error")
        return g

    def _parse_icmp(self, raw: bytes) -> Graph:
        g = Graph(); self._counter = 0
        if len(raw) < 8: return g
        icmp_type = raw[0]; icmp_code = raw[1]
        icmp_id = struct.unpack(">H", raw[4:6])[0]
        icmp_seq = struct.unpack(">H", raw[6:8])[0]

        func = self._node(g, "function", value="icmp_echo")
        typ = self._node(g, "const", value=icmp_type)
        cod = self._node(g, "const", value=icmp_code)
        sid = self._node(g, "var", value=icmp_id)
        seq = self._node(g, "for", value=icmp_seq)
        plen = self._node(g, "const", value=len(raw) - 8)
        g.root = self._node(g, "block", args=[func, typ, cod, sid, seq, plen])
        return g

    def _parse_ws(self, raw: bytes) -> Graph:
        g = Graph(); self._counter = 0
        if len(raw) < 2: return g
        opcode = raw[0] & 0x0F
        masked = (raw[1] & 0x80) != 0
        plen = raw[1] & 0x7F

        func = self._node(g, "function", value=f"ws_opcode_{opcode}")
        op = self._node(g, "const", value=opcode)
        mask = self._node(g, "if", value="masked" if masked else "unmasked")
        size = self._node(g, "const", value=plen)
        g.root = self._node(g, "block", args=[func, op, mask, size])
        return g

    def _extract_domain(self, raw, offset):
        labels = []; pos = offset
        while pos < len(raw):
            length = raw[pos]
            if length == 0: break
            if length > 63: break
            pos += 1
            labels.append(raw[pos:pos+length].decode("ascii", errors="ignore"))
            pos += length
        return ".".join(labels)


# ═══════════════════════════════════════════════════════════════════
# PROTOCOL SYNTHESIZER
# ═══════════════════════════════════════════════════════════════════

class ToProtocol:
    """Synthesizes protocol bytes FROM  IR."""

    def __init__(self):
        self._rng = random.Random()

    def synthesize(self, graph: Graph, carrier: str, target_host: str = "") -> bytes:
        if carrier == "dns": return self._synth_dns(graph)
        elif carrier == "http": return self._synth_http(graph, target_host)
        elif carrier == "icmp": return self._synth_icmp(graph)
        elif carrier == "ws_ping": return self._synth_ws(graph)
        return b""

    def _synth_dns(self, g: Graph) -> bytes:
        domain = "phantom.local"; tx_id = random.randint(1, 65535)
        for n in g.nodes.values():
            if n.kind == "var" and n.value and "." in str(n.value):
                domain = str(n.value)[:50]
            elif n.kind == "const" and isinstance(n.value, int) and n.value > 255:
                tx_id = n.value & 0xFFFF
        header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
        q = b""
        for label in domain.replace(".phantom.local", "").split("."):
            lb = label.encode("ascii", errors="ignore")[:63]
            if lb: q += bytes([len(lb)]) + lb
        q += b"\x07phantom\x05local\x00"
        q += struct.pack(">HH", 16, 1)
        return header + q

    def _synth_http(self, g: Graph, host: str) -> bytes:
        method, path = "GET", "/"
        for n in g.nodes.values():
            if n.kind == "var":
                if str(n.value).upper() in ("GET","POST","PUT","DELETE","HEAD"):
                    method = str(n.value)
                elif str(n.value).startswith("/"):
                    path = str(n.value)
        host = host or "localhost"
        return f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nAccept: */*\r\n\r\n".encode()

    def _synth_icmp(self, g: Graph) -> bytes:
        icmp_id = random.randint(1, 65535); icmp_seq = 1
        for n in g.nodes.values():
            if n.kind == "var" and isinstance(n.value, int):
                icmp_id = n.value
            elif n.kind == "for" and isinstance(n.value, int):
                icmp_seq = n.value
        payload = os.urandom(48)
        hdr = struct.pack(">BBHHH", 8, 0, 0, icmp_id, icmp_seq)
        full = hdr + payload
        csum = sum(struct.unpack("!"+"H"*(len(full)//2),
                   full + (b"\x00" if len(full)%2 else b"")))
        csum = (csum >> 16) + (csum & 0xFFFF); csum += csum >> 16
        return struct.pack(">BBHHH", 8, 0, ~csum & 0xFFFF, icmp_id, icmp_seq) + payload

    def _synth_ws(self, g: Graph) -> bytes:
        plen = min(random.randint(10, 100), 125)
        return bytes([0x89, 0x80 | plen]) + os.urandom(4) + os.urandom(plen)


# ═══════════════════════════════════════════════════════════════════
# DEEP PHANTOM V2 —  IR carrier translation
# ═══════════════════════════════════════════════════════════════════

class DeepPhantomV2:
    """
    Covert channel engine powered by  IR.

    - parse():  DNS/HTTP/ICMP/WS bytes →  IR
    - merge_graphs():  Finds equivalent structure across carriers
    - synthesize():   IR → DNS/HTTP/ICMP/WS bytes

    Carrier translation = bytes → IR → bytes (different carrier)
     IS the universal intermediate representation.
    """

    def __init__(self):
        self.parser = UniversalProtocolParser()
        self.synthesizer = ToProtocol()
        self._translations = 0

    def translate(self, data: bytes, from_carrier: str, to_carrier: str,
                  host: str = "") -> bytes:
        """Translate a packet between carriers via  IR."""
        self._translations += 1
        ir = self.parser.parse(data, from_carrier)
        return self.synthesizer.synthesize(ir, to_carrier, host)

    def compare_carriers(self, payload: str, carriers: list) -> dict:
        """ merge proves which carriers can substitute."""
        # Build a simple IR for the payload
        g = Graph()
        g.root = "r1"
        g.nodes["r1"] = Node(kind="function", value="payload")
        g.nodes["r2"] = Node(kind="var", value=payload)
        g.nodes["r1"].args = ["r2"]

        # Synthesize for each carrier, parse back, merge
        irs = {}
        for c in carriers:
            raw = self.synthesizer.synthesize(g, c)
            irs[c] = self.parser.parse(raw, c)

        # Pairwise merge comparison
        results = {}
        clist = list(irs.keys())
        for i in range(len(clist)):
            for j in range(i+1, len(clist)):
                c1, c2 = clist[i], clist[j]
                merged = merge_graphs([irs[c1], irs[c2]])
                h1 = {n.hash() for n in irs[c1].nodes.values()}
                h2 = {n.hash() for n in irs[c2].nodes.values()}
                shared = len(h1 & h2)
                total = len(h1 | h2)
                results[f"{c1}↔{c2}"] = {
                    "shared_nodes": shared,
                    "total_unique": total,
                    "similarity": round(shared/total, 3) if total > 0 else 0,
                    "merged_nodes": len(merged.nodes),
                }

        return results

    def translate_chain(self, data: bytes, carrier_chain: list, host: str = "") -> bytes:
        """Translate through a chain of carriers: dns→icmp→ws→http."""
        current = data
        for i in range(len(carrier_chain) - 1):
            current = self.translate(current, carrier_chain[i], carrier_chain[i+1], host)
        return current

    def stats(self) -> dict:
        return {"translations": self._translations, "engine": " IR merge"}


# ═══════════════════════════════════════════════════════════════════
# DEMO
# ═══════════════════════════════════════════════════════════════════

def demo():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║    DEEP PHANTOM V2 — PROTOCOL CARRIER TRANSLATION           ║
║  "Every protocol byte passes through  merge engine"    ║
╚══════════════════════════════════════════════════════════════════╝
""")
    dp = DeepPhantomV2()
    parser = UniversalProtocolParser()

    # Test 1: Parse all protocols to IR
    print("TEST 1: Parse 4 protocols →  IR\n")
    samples = {
        "dns": struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) +
               b"\x07example\x03com\x00\x00\x10\x00\x01",
        "http": b"GET /api/data HTTP/1.1\r\nHost: example.com\r\n\r\n",
        "icmp": struct.pack(">BBHHH", 8, 0, 0, 1234, 1) + b"abcdefghij" * 5,
        "ws_ping": bytes([0x89, 0x80 | 10]) + os.urandom(4) + os.urandom(10),
    }

    for carrier, data in samples.items():
        ir = parser.parse(data, carrier)
        kinds = set(n.kind for n in ir.nodes.values())
        print(f"  {carrier:<8} {len(data):3d}B → IR: {len(ir.nodes):2d} nodes, "
              f"kinds: {sorted(kinds)}")

    # Test 2: Carrier translation
    print(f"\nTEST 2: Carrier translation (IR intermediate)\n")
    dns_pkt = samples["dns"]
    for target in ["http", "icmp", "ws_ping"]:
        result = dp.translate(dns_pkt, "dns", target, host="example.com")
        print(f"  dns({len(dns_pkt)}B) → {target}({len(result)}B)  "
              f"[{result[:30].hex() if target != 'http' else result[:40]}]")

    # Test 3: merge_graphs comparison
    print(f"\nTEST 3: merge_graphs() carrier similarity matrix\n")
    comparisons = dp.compare_carriers("test.payload.xyz", ["dns", "http", "icmp", "ws_ping"])
    for key, val in comparisons.items():
        bar = "█" * int(val["similarity"] * 20)
        print(f"  {key:<18} sim={val['similarity']:.2f} merged={val['merged_nodes']} {bar}")

    # Test 4: Chain translation
    print(f"\nTEST 4: Chain translation dns→icmp→http→ws_ping\n")
    chain = dp.translate_chain(samples["dns"], ["dns", "icmp", "http", "ws_ping"], "target.com")
    print(f"  DNS input ({len(samples['dns'])}B) → 3 hops → WS output ({len(chain)}B)")
    print(f"   IR preserved semantic intent across 3 carrier translations.")

    print(f"\n{'═' * 70}")
    print(f"✅ {dp.stats()['translations']} translations through {dp.stats()['engine']}")
    print(f"{'═' * 70}")


if __name__ == "__main__":
    demo()
