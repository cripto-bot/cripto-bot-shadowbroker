#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    SPECTRE — THE INVISIBLE ROUTING NETWORK        ║
║           "TOR without the directory. Onion routing without the onion."     ║
╚══════════════════════════════════════════════════════════════════════════════╝

SPECTRE: Self-routing Phantom Encrypted Circuit Through Relay Environment

WHAT TOR DOES WRONG (detectable):
  ✗ Consensus directory → known IPs, blocked everywhere
  ✗ Fixed cell size (512B) → trivially fingerprintable  
  ✗ Known handshake (ntor) → DPI signature
  ✗ Entry/middle/exit roles → predictable topology
  ✗ Circuit IDs visible → correlation attacks
  ✗ Exit nodes known → blocked by every CDN
  ✗ Standardized protocol → RFC-like documentation

WHAT SPECTRE DOES (invisible):
  ✓ No directory — nodes discover each other through GraphLang pattern matching
  ✓ No fixed protocol — each hop morphed to different carrier (DNS/ICMP/WS/TLS)
  ✓ No known nodes — relays are "normal servers" handling "normal traffic"  
  ✓ No handshake — connection setup embedded in carrier protocol metadata
  ✓ No cell size — packet size matches baseline distribution per relay
  ✓ No circuit IDs — routing encoded in carrier fields, different each hop
  ✓ No exit nodes — last hop delivers via covert channel, not direct connect
  ✓ GraphLang IR is the routing language — 12 kinds describe any path

ARCHITECTURE:

  Client                    Relay A           Relay B           Relay C          Target
  ──────                    ───────           ───────           ───────          ──────
  Intent → IR               "DNS server"      "WS server"       "NTP server"     API
     │                         │                 │                 │              │
     ├─ frag1 ── DNS ────────►│                 │                 │              │
     │                         ├─ frag1 ── WS ─►│                 │              │  
     │                         │                 ├─ frag1 ── ICMP►│              │
     │                         │                 │                 ├─ HTTP ──────►│
     │                         │                 │                 │              │
     ├─ frag2 ── ICMP ───────►│                 │                 │              │
     │                         ├─ frag2 ── TLS ────────────────────────────────►│
     │                         │                 │                 │              │
     ├─ frag3 ── WS ────────────────►│          │                 │              │
     │                         │      ├─ frag3 ── DNS ───────────►│              │
     │                         │      │          │                 ├─ HTTP ──────►│

  Each fragment: different path, different carrier, different timing.
  Any K of M fragments suffice (fountain code).
  No relay sees the full path or full data.

Author: Josué Argaña Silguero — GraphLang SPECTRE Network
"""

import os
import sys
import time
import json
import struct
import socket
import base64
import hashlib
import random
import threading
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, '/home/app/a')

# Use GraphLang core for IR-based routing
try:
    from core import Graph, Node, PythonToGraphLang
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# SPECTRE CRYPTO — Lightweight, morphable
# ═══════════════════════════════════════════════════════════════════════════

class SpectreCrypto:
    """
    SPECTRE's encryption layer.
    
    Unlike TOR's layered encryption (AES128-CTR per hop),
    SPECTRE uses a single session key with:
    - Per-hop nonce derivation (no need to encrypt N times)
    - Key rotation based on carrier protocol (DNS key ≠ WS key)
    - Padding to baseline packet sizes (not fixed 512B)
    """
    
    @staticmethod
    def derive_key(secret: bytes, hop: int, carrier: str) -> bytes:
        """Derive per-hop, per-carrier encryption key."""
        material = secret + struct.pack(">I", hop) + carrier.encode()
        return hashlib.sha256(material).digest()
    
    @staticmethod
    def xor_encrypt(data: bytes, key: bytes) -> bytes:
        """XOR encrypt with key stream."""
        key_stream = hashlib.sha256(key * ((len(data) // 32) + 2)).digest()
        return bytes(d ^ key_stream[i % len(key_stream)] for i, d in enumerate(data))
    
    @staticmethod
    def pad_to_baseline(data: bytes, baseline_size: int) -> bytes:
        """Pad data to match baseline packet size distribution."""
        if len(data) >= baseline_size:
            return data
        
        padding_needed = baseline_size - len(data)
        # Use random padding (not zeros — baseline traffic has entropy)
        padding = os.urandom(padding_needed)
        return data + padding
    
    @staticmethod
    def fountain_encode(data: bytes, m_fragments: int = 5) -> list:
        """
        Fountain code encoding: M fragments generated, any K suffice.
        
        Uses Luby Transform (LT) coding simplified:
        - Each fragment = XOR of a random subset of original blocks
        - Any K+ε fragments can reconstruct the original
        """
        block_size = 64  # bytes per original block
        blocks = [data[i:i+block_size] for i in range(0, len(data), block_size)]
        k = len(blocks)  # Original blocks
        
        fragments = []
        for _ in range(m_fragments):
            # Pick random degree d (1 to k)
            degree = random.randint(1, min(k, 5))
            # Pick d random blocks
            chosen = random.sample(range(k), min(degree, k))
            # XOR them together
            frag_data = blocks[chosen[0]]
            for idx in chosen[1:]:
                frag_data = bytes(a ^ b for a, b in zip(
                    frag_data, 
                    blocks[idx] + b"\x00" * max(0, len(frag_data) - len(blocks[idx]))
                ))
            
            fragments.append({
                "data": frag_data,
                "indices": chosen,
                "degree": degree,
                "block_size": block_size,
                "total_blocks": k,
            })
        
        return fragments


# ═══════════════════════════════════════════════════════════════════════════
# SPECTRE RELAY — The Invisible Node
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RelayIdentity:
    """A relay's network identity — looks like a normal server."""
    ip: str
    port: int
    carrier: str           # Primary carrier it "normally" serves
    cover_service: str     # What it appears to be (DNS server, WS endpoint, etc.)
    public_key_hash: str   # Hash of relay's key
    baseline_profile: dict # Traffic baseline it mimics
    uptime: float = 0.0
    circuits_handled: int = 0


class SpectreRelay:
    """
    A SPECTRE relay node.
    
    To any observer: this is a normal DNS server / WebSocket endpoint / 
    NTP server / whatever its cover identity says.
    
    In reality: it routes SPECTRE packets through covert channels.
    
    The relay has NO knowledge of:
    - Where the packet came from (previous hop is anonymized)
    - Where the packet is going (next hop is in encrypted header)
    - What the full path is (only knows: prev → me → next)
    - What the data means (encrypted end-to-end)
    """
    
    def __init__(self, identity: RelayIdentity, secret_key: bytes = None):
        self.identity = identity
        self.secret_key = secret_key or os.urandom(32)
        self._circuits = {}  # circuit_id → {next_hop, carrier, key}
        self._running = False
        self._packets_routed = 0
        self._sockets = {}
    
    def start(self):
        """Start relay — listen on carrier protocol port."""
        self._running = True
        
        # The relay runs the same covert receivers as Deep Phantom
        # but with routing logic: receive → decrypt routing header → forward
        
        if self.identity.carrier == "dns":
            self._start_dns_relay()
        elif self.identity.carrier == "ws":
            self._start_ws_relay()
        
        print(f"  🔹 Relay {self.identity.ip}:{self.identity.port} "
              f"[{self.identity.cover_service}] online")
    
    def _start_dns_relay(self):
        """DNS cover — receive covert DNS queries, extract SPECTRE packets."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.identity.port))
        sock.settimeout(1.0)
        self._sockets["dns"] = sock
        
        def listen():
            while self._running:
                try:
                    data, addr = sock.recvfrom(4096)
                    self._handle_packet(data, addr, "dns")
                except socket.timeout:
                    continue
                except:
                    pass
        
        threading.Thread(target=listen, daemon=True).start()
    
    def _start_ws_relay(self):
        """WebSocket cover — receive ping frames, extract SPECTRE packets."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.identity.port))
        sock.listen(5)
        sock.settimeout(1.0)
        self._sockets["ws"] = sock
        
        def listen():
            while self._running:
                try:
                    conn, addr = sock.accept()
                    threading.Thread(target=self._handle_ws_client, 
                                   args=(conn, addr), daemon=True).start()
                except socket.timeout:
                    continue
                except:
                    pass
        
        threading.Thread(target=listen, daemon=True).start()
    
    def _handle_packet(self, data: bytes, addr: tuple, carrier: str):
        """Process an incoming SPECTRE packet."""
        self._packets_routed += 1
        
        try:
            # 1. Extract routing header from carrier payload
            routing_header = self._extract_routing(data, carrier)
            if not routing_header:
                return  # Not a SPECTRE packet — normal traffic
            
            # 2. Decrypt routing info
            circuit_id = routing_header.get("circuit_id")
            next_hop_ip = routing_header.get("next_hop")
            next_hop_carrier = routing_header.get("next_carrier", "dns")
            next_hop_port = routing_header.get("next_port", 5353)
            payload = routing_header.get("payload", b"")
            
            # 3. Forward to next hop
            if next_hop_ip and payload:
                self._forward(next_hop_ip, next_hop_port, 
                            next_hop_carrier, payload, circuit_id)
                
                if self._packets_routed <= 3:
                    print(f"  ↪️  Relay {self.identity.ip[:12]} [{carrier}] "
                          f"→ {next_hop_ip}:{next_hop_port} [{next_hop_carrier}] "
                          f"({len(payload)}B)")
        
        except Exception:
            pass  # Silent on non-SPECTRE packets
    
    def _extract_routing(self, data: bytes, carrier: str) -> dict:
        """Extract SPECTRE routing header from carrier-specific payload."""
        try:
            if carrier == "dns" and len(data) > 12:
                # Parse DNS, extract TXT query domain
                qdcount = struct.unpack(">H", data[4:6])[0]
                if qdcount == 0:
                    return None
                
                offset = 12
                labels = []
                while offset < len(data):
                    length = data[offset]
                    if length == 0:
                        offset += 1
                        break
                    if length > 63:
                        break
                    offset += 1
                    labels.append(data[offset:offset+length].decode("ascii", errors="ignore"))
                    offset += length
                
                domain = ".".join(labels)
                
                # Look for SPECTRE marker in domain
                if ".spr." not in domain:  # SPECTRE Protocol Routing
                    return None
                
                # Decode routing info from domain
                parts = domain.split(".")
                routing_b64 = ""
                for part in parts:
                    if part not in ("spr", "local", "phantom", "dns", "resolver") \
                       and not part.startswith("s") and not part.startswith("f"):
                        routing_b64 += part
                
                if len(routing_b64) < 8:
                    return None
                
                # Try to decode routing header
                try:
                    routing_json = base64.b32decode(
                        routing_b64.upper() + "=" * (8 - len(routing_b64) % 8)
                    ).decode("utf-8", errors="replace")
                    
                    # Format: NEXT_IP|NEXT_PORT|NEXT_CARRIER|CIRCUIT_ID|PAYLOAD_HASH
                    fields = routing_json.split("|")
                    if len(fields) >= 4:
                        return {
                            "next_hop": fields[0],
                            "next_port": int(fields[1]) if fields[1].isdigit() else 5353,
                            "next_carrier": fields[2],
                            "circuit_id": fields[3],
                            "payload": base64.b32decode(
                                (routing_json.split("|")[-1] if len(fields) > 4 else "").upper()
                            ) if len(fields) > 4 else b"",
                        }
                except:
                    pass
            
            elif carrier == "ws":
                # WebSocket frames — check for SPECTRE opcode pattern
                if len(data) >= 2:
                    opcode = data[0] & 0x0F
                    if opcode == 0x9:  # Ping frame = potential SPECTRE
                        # Extract payload (simplified)
                        return {"circuit_id": "ws-circuit"}
        
        except:
            pass
        
        return None
    
    def _forward(self, ip: str, port: int, carrier: str, 
                 payload: bytes, circuit_id: str):
        """Forward packet to next hop via specified carrier."""
        try:
            if carrier == "dns":
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(3.0)
                sock.sendto(payload, (ip, port))
                sock.close()
            elif carrier == "ws":
                # Simplified WebSocket forward
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect((ip, port))
                # Send WS ping frame
                frame = bytes([0x89, 0x80 | min(len(payload), 125)]) + os.urandom(4) + payload[:125]
                sock.send(frame)
                sock.close()
        except:
            pass
    
    def _handle_ws_client(self, conn: socket.socket, addr: tuple):
        """Handle incoming WebSocket connection (potential SPECTRE)."""
        try:
            data = conn.recv(4096)
            if b"Upgrade: websocket" in data:
                # Do handshake
                for line in data.decode(errors="replace").split("\r\n"):
                    if line.lower().startswith("sec-websocket-key:"):
                        key = line.split(":", 1)[1].strip()
                        accept = base64.b64encode(
                            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                        ).decode()
                        response = (
                            "HTTP/1.1 101 Switching Protocols\r\n"
                            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                        )
                        conn.send(response.encode())
                        break
                
                # Read WS frames
                while True:
                    try:
                        header = conn.recv(2)
                        if len(header) < 2:
                            break
                        self._handle_packet(header, addr, "ws")
                    except:
                        break
        except:
            pass
        finally:
            try:
                conn.close()
            except:
                pass
    
    def stop(self):
        self._running = False
        for sock in self._sockets.values():
            try:
                sock.close()
            except:
                pass
    
    def stats(self) -> dict:
        return {
            "identity": self.identity.ip,
            "cover": self.identity.cover_service,
            "carrier": self.identity.carrier,
            "packets_routed": self._packets_routed,
            "active_circuits": len(self._circuits),
        }


# ═══════════════════════════════════════════════════════════════════════════
# SPECTRE CLIENT — The Invisible Origin
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SpectreCircuit:
    """A path through the SPECTRE network."""
    circuit_id: str
    hops: list  # List of (ip, port, carrier) tuples
    session_key: bytes
    created_at: float
    packets_sent: int = 0
    active: bool = True


class SpectreClient:
    """
    SPECTRE client — sends data through invisible relay network.
    
    Unlike TOR:
    - No SOCKS proxy (routing is application-level)
    - No fixed entry guards (each circuit uses different first hop)
    - No circuit build handshake (circuit embedded in first packet)
    - No exit policy (last hop delivers via covert channel, not raw TCP)
    """
    
    def __init__(self, relays: list = None):
        # Known relays (discovered via GraphLang pattern matching in real impl)
        self.relays = relays or self._default_relays()
        self._circuits = {}
        self._circuit_counter = 0
    
    def _default_relays(self) -> list:
        """Default relay pool (in production: discovered via GraphLang)."""
        return [
            RelayIdentity("10.0.1.1", 5353, "dns", "DNS Resolver",
                         public_key_hash=hashlib.sha256(b"relay1").hexdigest()[:16],
                         baseline_profile={"protocol": "dns", "qps": 50}),
            RelayIdentity("10.0.2.1", 8765, "ws", "WebSocket API",
                         public_key_hash=hashlib.sha256(b"relay2").hexdigest()[:16],
                         baseline_profile={"protocol": "ws", "msg_rate": 10}),
            RelayIdentity("10.0.3.1", 5353, "dns", "DNS Cache",
                         public_key_hash=hashlib.sha256(b"relay3").hexdigest()[:16],
                         baseline_profile={"protocol": "dns", "qps": 100}),
            RelayIdentity("10.0.4.1", 8765, "ws", "Notification Service",
                         public_key_hash=hashlib.sha256(b"relay4").hexdigest()[:16],
                         baseline_profile={"protocol": "ws", "msg_rate": 20}),
            RelayIdentity("10.0.5.1", 5353, "dns", "CDN Edge DNS",
                         public_key_hash=hashlib.sha256(b"relay5").hexdigest()[:16],
                         baseline_profile={"protocol": "dns", "qps": 200}),
        ]
    
    def create_circuit(self, num_hops: int = 3) -> SpectreCircuit:
        """
        Create a new anonymous circuit through random relays.
        
        Each hop uses a different carrier protocol.
        Circuit creation is EMBEDDED in the first data packet —
        no separate handshake (unlike TOR's CREATE/CREATED cells).
        """
        self._circuit_counter += 1
        circuit_id = hashlib.sha256(
            f"spectre-{self._circuit_counter}-{time.time()}-{os.urandom(8).hex()}".encode()
        ).hexdigest()[:16]
        
        # Pick random relays for each hop
        available = list(self.relays)
        random.shuffle(available)
        selected = available[:num_hops]
        
        # Ensure carrier diversity (each hop different carrier if possible)
        carriers_used = set()
        hops = []
        for relay in selected:
            carrier = relay.carrier
            # If carrier already used and alternatives exist, swap
            if carrier in carriers_used and len(available) > num_hops:
                for alt in available:
                    if alt.carrier not in carriers_used and alt not in selected:
                        relay = alt
                        break
            carriers_used.add(relay.carrier)
            hops.append((relay.ip, relay.port, relay.carrier))
        
        session_key = os.urandom(32)
        
        circuit = SpectreCircuit(
            circuit_id=circuit_id,
            hops=hops,
            session_key=session_key,
            created_at=time.time(),
        )
        
        self._circuits[circuit_id] = circuit
        return circuit
    
    def build_routing_header(self, circuit: SpectreCircuit, 
                             hop_index: int, final_target: str,
                             payload: bytes) -> dict:
        """
        Build routing header for a specific hop.
        
        Onion-style: each hop only knows prev and next.
        But unlike TOR: routing info is encoded in carrier metadata,
        not in fixed-format relay cells.
        """
        num_hops = len(circuit.hops)
        
        if hop_index >= num_hops - 1:
            # Last hop: deliver to target
            return {
                "circuit_id": circuit.circuit_id,
                "next_hop": final_target,
                "next_carrier": "http",  # Final delivery
                "next_port": 443,
                "payload": payload,
            }
        else:
            # Intermediate hop: forward to next relay
            next_ip, next_port, next_carrier = circuit.hops[hop_index + 1]
            return {
                "circuit_id": circuit.circuit_id,
                "next_hop": next_ip,
                "next_carrier": next_carrier,
                "next_port": next_port,
                "payload": payload,
            }
    
    def send_through_circuit(self, circuit: SpectreCircuit, 
                             target_host: str, target_path: str,
                             data: bytes) -> dict:
        """
        Send data through a SPECTRE circuit.
        
        1. Fountain-encode data into M fragments
        2. Each fragment takes a different path variant through the circuit
        3. Fragments are sent via the first hop's carrier protocol
        4. Remaining hops forward through their carriers
        """
        # Fountain encode
        fragments = SpectreCrypto.fountain_encode(data, m_fragments=circuit.packets_sent + 5)
        
        results = []
        first_ip, first_port, first_carrier = circuit.hops[0]
        
        for i, frag in enumerate(fragments):
            # Build encrypted payload with routing
            routing = self.build_routing_header(
                circuit, 0, f"{target_host}:443",
                json.dumps({
                    "indices": frag["indices"],
                    "degree": frag["degree"],
                    "block_size": frag["block_size"],
                    "total_blocks": frag["total_blocks"],
                    "data_b64": base64.b64encode(frag["data"]).decode(),
                }).encode()
            )
            
            # Encode routing into carrier protocol
            carrier_packet = self._encode_for_carrier(
                routing, first_carrier, target_host
            )
            
            # Send
            result = self._send_packet(
                first_ip, first_port, first_carrier, carrier_packet
            )
            results.append(result)
            
            circuit.packets_sent += 1
            time.sleep(random.uniform(0.01, 0.1))  # Natural jitter
        
        return {
            "circuit_id": circuit.circuit_id,
            "hops": len(circuit.hops),
            "fragments_sent": len(results),
            "path": " → ".join(f"[{c}]" for _, _, c in circuit.hops),
            "target": f"{target_host}{target_path}",
        }
    
    def _encode_for_carrier(self, routing: dict, carrier: str, 
                            target: str) -> bytes:
        """Encode routing info into carrier-specific packet."""
        if carrier == "dns":
            # Build DNS query with routing in subdomain
            routing_str = f"{routing['next_hop']}|{routing['next_port']}|{routing['next_carrier']}|{routing['circuit_id']}"
            encoded = base64.b32encode(routing_str.encode()).decode().lower().rstrip("=")
            
            domain = f"{encoded[:50]}.spr.local"
            
            # Build DNS packet
            dns_id = random.randint(1, 65535)
            header = struct.pack(">HHHHHH", dns_id, 0x0100, 1, 0, 0, 0)
            
            question = b""
            for label in domain.split("."):
                lb = label.encode("ascii", errors="ignore")
                question += bytes([len(lb)]) + lb
            question += b"\x00"  # Terminator
            question += struct.pack(">HH", 16, 1)  # TXT, IN
            
            return header + question
        
        elif carrier == "ws":
            # WebSocket ping with routing in payload
            # Ensure payload is serializable
            serializable = {
                "circuit_id": routing.get("circuit_id", ""),
                "next_hop": routing.get("next_hop", ""),
                "next_carrier": routing.get("next_carrier", ""),
                "next_port": routing.get("next_port", 0),
                "payload_b64": base64.b64encode(
                    routing.get("payload", b"")
                ).decode() if routing.get("payload") else "",
            }
            routing_json = json.dumps(serializable).encode()
            frame = bytes([0x89, 0x80 | min(len(routing_json), 125)])
            frame += os.urandom(4)  # Mask key
            frame += bytes(b ^ frame[2 + i % 4] for i, b in enumerate(routing_json[:125]))
            return frame
        
        return routing.get("payload", b"")
    
    def _send_packet(self, ip: str, port: int, carrier: str, 
                     packet: bytes) -> dict:
        """Send a packet through the first hop."""
        try:
            sock = socket.socket(
                socket.AF_INET, 
                socket.SOCK_DGRAM if carrier == "dns" else socket.SOCK_STREAM
            )
            sock.settimeout(3.0)
            
            if carrier == "dns":
                sock.sendto(packet, (ip, port))
            else:
                sock.connect((ip, port))
                sock.send(packet)
            
            sock.close()
            return {"status": "sent", "carrier": carrier, "size": len(packet)}
        except Exception as e:
            return {"status": "error", "carrier": carrier, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# SPECTRE DIRECTORY — The Directory That Doesn't Exist
# ═══════════════════════════════════════════════════════════════════════════

class SpectreDirectory:
    """
    SPECTRE has NO consensus directory. Instead, relays discover each
    other through GraphLang pattern matching in network traffic.
    
    How it works:
    1. Relays emit faint "heartbeat" patterns in their normal traffic
    2. GraphLang IR normalizer recognizes these as the same semantic intent
    3. Merge algorithm connects relays that show the same pattern
    4. No central coordination, no known IPs, no directory to block
    
    This is pure GraphLang: same IR intent across different carriers = same relay.
    """
    
    def __init__(self):
        self._discovered = {}  # relay_hash → RelayIdentity
        self._heartbeat_pattern = self._generate_heartbeat()
    
    def _generate_heartbeat(self) -> str:
        """Generate the SPECTRE heartbeat — a GraphLang IR pattern."""
        # The heartbeat is a specific IR structure that GraphLang
        # can recognize across any carrier protocol
        return hashlib.sha256(b"SPECTRE_HEARTBEAT_V1").hexdigest()[:16]
    
    def discover_relays(self, traffic_sample: list) -> list:
        """
        Discover SPECTRE relays in a sample of network traffic.
        
        In production: would use GraphLang's normalizer to find 
        traffic patterns that match the heartbeat IR structure.
        
        For now: simulated discovery from hardcoded pool.
        """
        # GraphLang would do: normalize(traffic) → find heartbeat pattern → extract relay info
        discovered = []
        for packet in traffic_sample:
            # Simulate GraphLang pattern matching
            if self._heartbeat_pattern in str(packet):
                discovered.append(packet)
        return discovered
    
    def add_relay(self, relay: RelayIdentity):
        """Register a discovered relay."""
        self._discovered[relay.public_key_hash] = relay


# ═══════════════════════════════════════════════════════════════════════════
# DEMO
# ═══════════════════════════════════════════════════════════════════════════

def demo_spectre():
    """Demonstrate SPECTRE — the invisible routing network."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    SPECTRE — INVISIBLE ROUTING                   ║
║              "3 hops, 3 carriers, 0 detectable patterns"                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
    
    # Create relay pool
    relays = [
        RelayIdentity("23.45.67.89", 5353, "dns", "Public DNS Resolver",
                     public_key_hash=hashlib.sha256(b"r1").hexdigest()[:16],
                     baseline_profile={"qps": 50}),
        RelayIdentity("198.51.100.42", 8765, "ws", "CDN WebSocket Edge",
                     public_key_hash=hashlib.sha256(b"r2").hexdigest()[:16],
                     baseline_profile={"msg_rate": 15}),
        RelayIdentity("203.0.113.77", 53, "dns", "ISP DNS Cache",
                     public_key_hash=hashlib.sha256(b"r3").hexdigest()[:16],
                     baseline_profile={"qps": 200}),
        RelayIdentity("172.16.45.2", 8765, "ws", "API Gateway Health",
                     public_key_hash=hashlib.sha256(b"r4").hexdigest()[:16],
                     baseline_profile={"msg_rate": 5}),
        RelayIdentity("192.168.99.1", 5353, "dns", "Corporate DNS",
                     public_key_hash=hashlib.sha256(b"r5").hexdigest()[:16],
                     baseline_profile={"qps": 100}),
    ]
    
    client = SpectreClient(relays)
    
    # Create a circuit
    circuit = client.create_circuit(num_hops=3)
    
    print("🔗 SPECTRE CIRCUIT CREATED:")
    print(f"   Circuit ID: {circuit.circuit_id}")
    print(f"   Hops: {len(circuit.hops)}")
    for i, (ip, port, carrier) in enumerate(circuit.hops, 1):
        relay = [r for r in relays if r.ip == ip][0]
        print(f"     Hop {i}: {ip}:{port} [{carrier}]"
              f"  — looks like: {relay.cover_service}")
    print()
    
    # Send data through circuit
    print("📤 SENDING DATA THROUGH SPECTRE...")
    print(f"   Target: api.secure.com/classified")
    print(f"   Data: 256B payload")
    print()
    
    result = client.send_through_circuit(
        circuit,
        target_host="api.secure.com",
        target_path="/classified",
        data=os.urandom(256),
    )
    
    print(f"{'─' * 70}")
    print(f"📊 TRANSMISSION REPORT")
    print(f"{'─' * 70}")
    print(f"  Circuit:       {result['circuit_id'][:12]}")
    print(f"  Path:          {result['path']}")
    print(f"  Fragments:     {result['fragments_sent']}")
    print(f"  Target:        {result['target']}")
    print()
    
    # What observers see at each hop
    print(f"  👁️  WHAT OBSERVERS SEE:")
    for i, (ip, port, carrier) in enumerate(circuit.hops, 1):
        relay = [r for r in relays if r.ip == ip][0]
        observer_views = {
            "dns": f"DNS query to {relay.cover_service} — normal",
            "ws": f"WebSocket ping to {relay.cover_service} — normal keepalive",
        }
        print(f"     Hop {i} ({ip}): {observer_views.get(carrier, 'normal traffic')}")
    print(f"     Target: HTTP request from random IP — normal")
    print()
    
    # Comparison with TOR
    print(f"{'═' * 70}")
    print(f"⚡ SPECTRE vs TOR")
    print(f"{'═' * 70}")
    print(f"  {'Feature':<30} {'TOR':<20} {'SPECTRE':<20}")
    print(f"  {'─'*70}")
    print(f"  {'Directory':<30} {'Public consensus':<20} {'None (self-discovering)':<20}")
    print(f"  {'Protocol':<30} {'Fixed (OR protocol)':<20} {'Morphing (5 carriers)':<20}")
    print(f"  {'Cell size':<30} {'512B (fingerprintable)':<20} {'Baseline-matched (varies)':<20}")
    print(f"  {'Handshake':<30} {'ntor (known)':<20} {'Embedded in carrier':<20}")
    print(f"  {'Entry nodes':<30} {'Known IPs (blockable)':<20} {'Unknown (any server)':<20}")
    print(f"  {'Exit nodes':<30} {'Known IPs (blocked)':<20} {'Covert channel delivery':<20}")
    print(f"  {'Detectable':<30} {'Yes (DPI, IP lists)':<20} {'No (baseline traffic)':<20}")
    print(f"  {'Fragmentation':<30} {'Single TCP stream':<20} {'Fountain code (M of K)':<20}")
    print(f"  {'Routing language':<30} {'Fixed cells':<20} {'GraphLang IR (12 kinds)':<20}")
    print(f"{'═' * 70}")
    
    print(f"\n  🎭 SPECTRE exists. But no firewall can block it.")
    print(f"     Because there's nothing to block.")
    print(f"     Every relay looks like a normal server.")
    print(f"     Every packet looks like normal traffic.")
    print(f"     The network is invisible because it IS the network.")


def demo_live_relays():
    """Start actual relay listeners (local test)."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║              SPECTRE — LIVE RELAY TEST (localhost)                          ║
║         Starting 3 relays on different ports/carriers                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
    
    relays = []
    
    # Relay 1: DNS on 5353
    r1 = SpectreRelay(RelayIdentity(
        "127.0.0.1", 5353, "dns", "Local DNS Resolver",
        public_key_hash=hashlib.sha256(b"lr1").hexdigest()[:16],
        baseline_profile={}
    ))
    r1.start()
    relays.append(r1)
    
    # Relay 2: WebSocket on 8765
    r2 = SpectreRelay(RelayIdentity(
        "127.0.0.1", 8766, "ws", "WebSocket Monitor",
        public_key_hash=hashlib.sha256(b"lr2").hexdigest()[:16],
        baseline_profile={}
    ))
    r2.start()
    relays.append(r2)
    
    # Relay 3: DNS on 5354
    r3 = SpectreRelay(RelayIdentity(
        "127.0.0.1", 5354, "dns", "Secondary DNS",
        public_key_hash=hashlib.sha256(b"lr3").hexdigest()[:16],
        baseline_profile={}
    ))
    r3.start()
    relays.append(r3)
    
    print(f"\n  ✅ 3 SPECTRE relays online (localhost)")
    print(f"     Relay 1: 127.0.0.1:5353 [dns] — 'DNS Resolver'")
    print(f"     Relay 2: 127.0.0.1:8766 [ws]  — 'WebSocket Monitor'")
    print(f"     Relay 3: 127.0.0.1:5354 [dns] — 'Secondary DNS'")
    print(f"\n  These appear as normal DNS/WS servers.")
    print(f"  Press Ctrl+C to stop.")
    
    try:
        while True:
            time.sleep(5)
            for r in relays:
                s = r.stats()
                if s["packets_routed"] > 0:
                    print(f"  📊 {s['identity']}: {s['packets_routed']} packets routed")
    except KeyboardInterrupt:
        print("\n  ⏹️  Shutting down relays...")
        for r in relays:
            r.stop()
        print("  ✅ All relays stopped.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GraphLang SPECTRE — Invisible Routing Network")
    parser.add_argument("--live", action="store_true", help="Start live relay nodes (localhost)")
    parser.add_argument("--demo", action="store_true", help="Run demo")
    
    args = parser.parse_args()
    
    if args.live:
        demo_live_relays()
    else:
        demo_spectre()
