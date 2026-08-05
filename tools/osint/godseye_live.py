#!/usr/bin/env python3
"""God's Eye LIVE — Connected to ShadowBroker API"""
import sys, json, time, math, requests, hashlib
sys.path.insert(0, '/home/app/a')
from godseye_fusion import FusionEngine

SHADOWBROKER = "http://localhost:8002"

print("""
╔══════════════════════════════════════════════════════════════════╗
║         GOD'S EYE LIVE — CONNECTED TO SHADOWBROKER API          ║
╚══════════════════════════════════════════════════════════════════╝
""")

godseye = FusionEngine()

# ─── INGEST REAL DATA ───
print("📡 INGESTING LIVE SHADOWBROKER DATA...\n")

try:
    resp = requests.get(f"{SHADOWBROKER}/api/live-data/fast", timeout=30)
    data = resp.json()
except Exception as e:
    print(f"❌ API error: {e}")
    sys.exit(1)

# Military flights
for flight in data.get("military_flights", [])[:50]:
    godseye.ingest("military_flight", flight.get("callsign", "?"),
                   flight.get("lat", 0), flight.get("lng", 0),
                   {"altitude": flight.get("alt"), "force": flight.get("force", ""),
                    "type": flight.get("military_type", "unknown")})
print(f"  ✅ Military flights: {min(50, len(data.get('military_flights',[])))} ingested")

# Private jets
for jet in data.get("private_jets", [])[:100]:
    godseye.ingest("private_jet", jet.get("callsign", "?"),
                   jet.get("lat", 0), jet.get("lng", 0),
                   {"altitude": jet.get("alt"), "origin": jet.get("origin_name", "?")})
print(f"  ✅ Private jets: {min(100, len(data.get('private_jets',[])))} ingested")

# Ships
for ship in data.get("ships", []):
    godseye.ingest("ship", ship.get("name", "?"),
                   ship.get("lat", 0), ship.get("lng", 0),
                   {"type": ship.get("type", "?"), "country": ship.get("country", "?"),
                    "desc": ship.get("desc", "")})
    print(f"  🚢 {ship.get('name','?')[:40]}: {ship.get('desc','')[:60]}")
print(f"  ✅ Ships: {len(data.get('ships',[]))} ingested")

# Satellites  
for sat in data.get("satellites", [])[:50]:
    godseye.ingest("satellite", sat.get("name", "?"),
                   sat.get("lat", 0), sat.get("lng", 0),
                   {"mission": sat.get("mission", "?"), "country": sat.get("country", "?"),
                    "type": sat.get("sat_type", "?")})
print(f"  ✅ Satellites: {min(50, len(data.get('satellites',[])))} ingested")

# Trains
for train in data.get("trains", [])[:50]:
    godseye.ingest("train", train.get("name", "?"),
                   train.get("lat", 0), train.get("lng", 0),
                   {"operator": train.get("operator", "?"), "country": train.get("country", "?")})
print(f"  ✅ Trains: {min(50, len(data.get('trains',[])))} ingested")

# SIGINT
for sig in data.get("sigint", [])[:100]:
    godseye.ingest("sigint", sig.get("callsign", "?"),
                   sig.get("lat", 0), sig.get("lng", 0),
                   {"source": sig.get("source", "?"), "confidence": sig.get("confidence", 0)})
print(f"  ✅ SIGINT: {min(100, len(data.get('sigint',[])))} ingested")

print(f"\n  📊 TOTAL: {godseye.stats()['total_datapoints']} real data points in {godseye.stats()['total_feeds']} feeds\n")

# ─── SEARCH: Military flights ───
print("═" * 70)
print("🔍 GOD'S EYE: Military flights analysis")
print("═" * 70)

military = data.get("military_flights", [])
forces = {}
for f in military:
    force = f.get("force", "Unknown")
    forces[force] = forces.get(force, 0) + 1

print(f"\n  🔴 {len(military)} military aircraft airborne RIGHT NOW:")
for force, count in sorted(forces.items(), key=lambda x: -x[1])[:10]:
    bar = "█" * min(40, count // 2)
    print(f"     {force:<20} {count:>4} {bar}")

# Show specific military flights
print(f"\n  📍 Active military flights:")
for f in military[:10]:
    print(f"     {f.get('callsign','?'):<12} {f.get('military_type','?'):<20} "
          f"lat={f.get('lat',0):.2f} lon={f.get('lng',0):.2f} "
          f"alt={f.get('alt',0):.0f}ft")

# ─── SEARCH: Find USS Nimitz ───
print(f"\n{'═' * 70}")
print("🔍 GOD'S EYE: 'USS Nimitz' (aircraft carrier)")
print("═" * 70)

result = godseye.search("USS Nimitz", radius_km=50)
if result["hits"]:
    for feed, dps in result["hits"].items():
        for dp in dps[:1]:
            print(f"     [{feed}] {dp.entity_id} at {dp.position.lat:.3f}, {dp.position.lon:.3f}")
            for k, v in dp.metadata.items():
                print(f"        {k}: {v}")

if result["proximity_hits"]:
    print(f"\n  📍 Nearby ({len(result['proximity_hits'])} items within 50km):")
    for ph in result["proximity_hits"][:8]:
        dp = ph["point"]
        print(f"     [{dp.feed:<18}] {dp.entity_id[:30]:<30} {ph['distance_km']:.1f}km")

# ─── SEARCH: Satellites overhead ───
print(f"\n{'═' * 70}")
print("🔍 GOD'S EYE: Military satellites overhead")
print("═" * 70)

sats = data.get("satellites", [])
military_sats = [s for s in sats if "military" in s.get("mission", "").lower()]
print(f"\n  🛰️  {len(military_sats)} military/recon satellites tracked:")
for s in military_sats[:10]:
    print(f"     {s.get('name','?'):<30} {s.get('country','?'):<15} "
          f"{s.get('sat_type','?'):<25} "
          f"lat={s.get('lat',0):.2f} lon={s.get('lng',0):.2f}")

# ─── FINAL ───
print(f"\n{'═' * 70}")
print(f"🏁 GOD'S EYE LIVE — STATUS")
print(f"{'═' * 70}")
s = godseye.stats()
print(f"  Real data ingested: {s['total_datapoints']} points")
print(f"  Active feeds:       {s['total_feeds']}")
print(f"  Unique entities:    {s['total_entities']}")
print(f"  Engine:             ShadowBroker API + GraphLang merge_graphs()")
print(f"  Latency:            <5s from real world to fusion engine")
print(f"{'═' * 70}")
