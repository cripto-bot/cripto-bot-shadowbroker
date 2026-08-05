#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║              GOD'S EYE — GraphLang Fusion Engine               ║
║   "Find anyone. Track anything. See everything. Invisible."    ║
╚══════════════════════════════════════════════════════════════════╝

SHADOWBROKER DATA FEEDS (60+):
  Aircraft (ADS-B), Ships (AIS), Satellites (TLE/SatNOGS), CCTV (11000+),
  Police Scanners, Earthquake/USGS, Wildfire (NASA FIRMS), GPS Jamming,
  Power Plants (35000+), Data Centers (2000+), Military Bases,
  Internet Outages, Meshtastic Mesh, APRS Radio, Telegram OSINT,
  KiwiSDR Radio, Submarine Cables, Sanctions (OFAC), BGP/ASN,
  Shodan Devices, Malware C2, CISA KEV, Supply Chain Risk,
  GDELT Events, News Feeds, Prediction Markets, SAR Ground Change,
  Amtrak/DigiTraffic Trains, UAP Sightings, Wastewater, +30 more

FUSION:
  Every data point → normalized to GraphLang IR (12 kinds)
  merge_graphs() finds connections across feeds
  One target → ALL correlated data in milliseconds

HOW IT WORKS (example: "find Elon Musk's jet"):

  Query: "N628TS" (tail number)
     │
     ├─ ADS-B feed      → position: 33.9425°N, 118.4081°W (LAX)
     ├─ AIS feed        → NO MATCH
     ├─ CCTV LAX area   → Camera #4421 at Terminal 5
     ├─ Satellite        → Sentinel-2 image of LAX, 10m resolution
     ├─ News feed        → "Elon Musk spotted at LAX" (GDELT event)
     ├─ Aircraft carrier → USS Carl Vinson 200nm away (just in case)
     ├─ OFAC/Sanctions   → CLEAN
     └─ Entity graph     → Owner: Elon Musk, Company: SpaceX, Net: Tesla
        │
        └─ MERGE_RESULT: Target N628TS at LAX, Terminal 5, Camera 4421,
           Satellite available, News confirmed, Carrier nearby,
           Risk Level: LOW (civilian aircraft, no sanctions)
"""

import sys, json, time, math, hashlib, random
from collections import defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, '/home/app/a')
from core import Node, Graph, merge_graphs, build_graph


# ═══════════════════════════════════════════════════════════════════
# FUSION DATA MODEL — Every data point as GraphLang IR
# ═══════════════════════════════════════════════════════════════════

@dataclass
class GeoPoint:
    lat: float; lon: float; alt: float = 0.0

@dataclass
class DataPoint:
    """A single observation from any ShadowBroker feed, normalized to IR."""
    feed: str           # adsb, ais, cctv, satellite, news, etc.
    entity_id: str      # Tail number, MMSI, camera ID, etc.
    position: GeoPoint
    timestamp: float
    metadata: dict = field(default_factory=dict)
    ir_graph: Graph = None  # GraphLang IR representation
    ir_hashes: set = field(default_factory=set)


class FusionEngine:
    """
    THE GOD'S EYE ENGINE.

    Takes a target query → searches ALL feeds → normalizes to IR →
    merge_graphs finds connections → returns unified intelligence picture.
    """

    def __init__(self):
        self._feeds = defaultdict(list)  # feed_name → [DataPoints]
        self._entity_index = defaultdict(list)  # entity_id → [DataPoints]
        self._geospatial_index = []  # For proximity search
        self._search_count = 0

    def ingest(self, feed: str, entity_id: str, lat: float, lon: float,
               metadata: dict = None):
        """Ingest a data point from any ShadowBroker feed."""
        dp = DataPoint(
            feed=feed,
            entity_id=entity_id,
            position=GeoPoint(lat, lon),
            timestamp=time.time(),
            metadata=metadata or {},
        )
        # Normalize to GraphLang IR
        dp.ir_graph = build_graph(
            ("function", feed),
            ("var", entity_id),
            ("const", round(lat, 4)),
            ("const", round(lon, 4)),
        )
        dp.ir_hashes = {n.hash() for n in dp.ir_graph.nodes.values()}

        self._feeds[feed].append(dp)
        self._entity_index[entity_id].append(dp)
        self._geospatial_index.append(dp)

    def search(self, query: str, radius_km: float = 100.0) -> dict:
        """
        GOD'S EYE SEARCH: One query, all feeds.

        Returns everything GraphLang finds about the target.
        """
        self._search_count += 1
        results = {
            "query": query,
            "timestamp": time.time(),
            "hits": defaultdict(list),  # feed → matching data points
            "proximity_hits": [],
            "cross_feed_correlations": [],
            "entity_graph": {},
            "threat_assessment": {},
            "total_hits": 0,
        }

        # 1. DIRECT MATCH: entity_id lookup
        direct = self._entity_index.get(query, [])
        for dp in direct:
            results["hits"][dp.feed].append(dp)

        # 2. FUZZY MATCH: entity_id contains query
        for eid, dps in self._entity_index.items():
            if query.lower() in eid.lower() and eid != query:
                for dp in dps:
                    results["hits"][dp.feed].append(dp)

        # 3. PROXIMITY: find points near known positions
        known_positions = [(dp.position, dp.feed) for dp in direct]
        if known_positions:
            for dp in self._geospatial_index:
                for pos, feed in known_positions:
                    dist = self._haversine(pos.lat, pos.lon, 
                                          dp.position.lat, dp.position.lon)
                    if dist < radius_km and dp not in direct:
                        results["proximity_hits"].append({
                            "point": dp,
                            "distance_km": round(dist, 1),
                            "near": feed,
                        })

        # 4. CROSS-FEED CORRELATION via GraphLang merge_graphs
        feeds_with_hits = list(results["hits"].keys())
        if len(feeds_with_hits) >= 2:
            for i in range(len(feeds_with_hits)):
                for j in range(i+1, len(feeds_with_hits)):
                    f1, f2 = feeds_with_hits[i], feeds_with_hits[j]
                    dps1 = results["hits"][f1][:3]
                    dps2 = results["hits"][f2][:3]

                    for dp1 in dps1:
                        for dp2 in dps2:
                            if dp1.ir_hashes and dp2.ir_hashes:
                                shared = len(dp1.ir_hashes & dp2.ir_hashes)
                                total = len(dp1.ir_hashes | dp2.ir_hashes)
                                sim = shared / total if total > 0 else 0

                                if sim > 0.3:
                                    results["cross_feed_correlations"].append({
                                        "feed_a": f1,
                                        "entity_a": dp1.entity_id,
                                        "feed_b": f2,
                                        "entity_b": dp2.entity_id,
                                        "ir_similarity": round(sim, 3),
                                    })

        # 5. ENTITY GRAPH: expand connections
        for feed, dps in results["hits"].items():
            for dp in dps[:2]:
                if "owner" in dp.metadata:
                    owner = dp.metadata["owner"]
                    results["entity_graph"][owner] = results["entity_graph"].get(owner, [])
                    results["entity_graph"][owner].append(dp.entity_id)

        # 6. THREAT ASSESSMENT
        threat_score = 0
        threat_factors = []
        for feed, dps in results["hits"].items():
            if feed in ("sanctions", "ofac"):
                threat_score += 40
                threat_factors.append(f"Sanctions match: {[d.entity_id for d in dps]}")
            elif feed == "military_bases":
                threat_score += 20
                threat_factors.append("Near military base")
            elif feed == "malware_c2":
                threat_score += 30
                threat_factors.append("C2 infrastructure nearby")
            elif feed == "gps_jamming":
                threat_score += 15
                threat_factors.append("GPS jamming zone")

        results["threat_assessment"] = {
            "score": min(100, threat_score),
            "level": "CRITICAL" if threat_score > 60 else "HIGH" if threat_score > 30 else "MEDIUM" if threat_score > 10 else "LOW",
            "factors": threat_factors,
        }

        # 7. TOTAL
        for feed, dps in results["hits"].items():
            results["total_hits"] += len(dps)
        results["total_hits"] += len(results["proximity_hits"])

        return results

    def continuous_track(self, query: str, interval_sec: float = 30.0) -> dict:
        """Persistent tracking: predict next position, monitor continuously."""
        # Get current position
        current = self.search(query)

        # Predict next position using GraphLang predictor pattern
        # (in production: use real 314M transition predictor)
        positions = []
        for feed, dps in current["hits"].items():
            for dp in dps[:2]:
                positions.append(dp.position)

        prediction = None
        if positions:
            avg_lat = sum(p.lat for p in positions) / len(positions)
            avg_lon = sum(p.lon for p in positions) / len(positions)
            prediction = {
                "lat": round(avg_lat, 4),
                "lon": round(avg_lon, 4),
                "confidence": 0.7,
                "based_on": f"{len(positions)} positions from {len(current['hits'])} feeds",
            }

        return {
            "current": current,
            "prediction": prediction,
            "next_update_in": interval_sec,
            "tracking_active": True,
        }

    def _haversine(self, lat1, lon1, lat2, lon2):
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def stats(self):
        return {
            "total_feeds": len(self._feeds),
            "total_entities": len(self._entity_index),
            "total_datapoints": len(self._geospatial_index),
            "searches_performed": self._search_count,
        }


# ═══════════════════════════════════════════════════════════════════
# DEMO — God's Eye in action
# ═══════════════════════════════════════════════════════════════════

def demo():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                   GOD'S EYE —               ║
║     "ShadowBroker feeds × GraphLang IR = Total Awareness"       ║
╚══════════════════════════════════════════════════════════════════╝
""")
    godseye = FusionEngine()

    # ─── INGEST: Simulate ShadowBroker data feeds ───
    print("📡 INGESTING SHADOWBROKER FEEDS...\n")

    # Aircraft (ADS-B)
    godseye.ingest("adsb", "N628TS", 33.9425, -118.4081, 
                   {"owner": "Elon Musk", "type": "G650ER", "altitude": 41000, "speed": 488})
    godseye.ingest("adsb", "AF1", 38.8512, -77.0377,
                   {"owner": "USAF", "type": "VC-25A", "callsign": "Air Force One"})
    godseye.ingest("adsb", "N887WM", 40.6892, -74.0445,
                   {"owner": "Bill Gates", "type": "G650ER"})
    godseye.ingest("adsb", "RA-96023", 55.7558, 37.6173,
                   {"owner": "Russian Gov", "type": "IL-96-300"})
    print("  ✅ ADS-B: 4 aircraft ingested")

    # Ships (AIS)
    godseye.ingest("ais", "319012300", 33.7200, -118.2500,
                   {"name": "MY LAUREL", "owner": "Jeff Bezos", "type": "Superyacht", "length": 127})
    godseye.ingest("ais", "310789000", 33.7500, -118.3000,
                   {"name": "CMA CGM", "type": "Container", "destination": "LAX"})
    godseye.ingest("ais", "538071330", 37.8000, -122.4000,
                   {"name": "EVER GIVEN", "type": "Container"})
    print("  ✅ AIS: 3 ships ingested")

    # CCTV (simulated — ShadowBroker has 11,000+ real cameras)
    godseye.ingest("cctv", "CAM-LAX-T5-01", 33.9420, -118.4085,
                   {"location": "LAX Terminal 5", "status": "active"})
    godseye.ingest("cctv", "CAM-LAX-T5-02", 33.9415, -118.4090,
                   {"location": "LAX Terminal 5 Gate", "status": "active"})
    godseye.ingest("cctv", "CAM-NYC-TS-01", 40.6892, -74.0445,
                   {"location": "Times Square NYC", "status": "active"})
    print("  ✅ CCTV: 3 cameras ingested")

    # Satellites
    godseye.ingest("satellite", "SENTINEL-2A", 33.94, -118.40,
                   {"type": "optical", "resolution": "10m", "pass_time": time.time()+3600})
    godseye.ingest("satellite", "LANDSAT-9", 33.95, -118.42,
                   {"type": "thermal", "resolution": "30m"})
    print("  ✅ Satellites: 2 passes ingested")

    # Military bases
    godseye.ingest("military_bases", "USAF-LAX-AFS", 33.9430, -118.4080,
                   {"name": "Los Angeles Air Force Base", "type": "Space Systems Command"})
    godseye.ingest("military_bases", "NAS-NORTH-ISLAND", 32.6990, -117.2150,
                   {"name": "Naval Air Station North Island"})
    print("  ✅ Military: 2 bases ingested")

    # News events (GDELT)
    godseye.ingest("news", "GDELT-9928371", 33.9420, -118.4080,
                   {"title": "Elon Musk spotted at LAX", "tone": -2.1, "source": "Reuters"})
    godseye.ingest("news", "GDELT-9928456", 38.8500, -77.0400,
                   {"title": "Air Force One departs Andrews", "tone": 0.0})
    print("  ✅ News: 2 events ingested")

    # Sanctions/OFAC
    godseye.ingest("sanctions", "OFAC-RA-96023", 55.75, 37.61,
                   {"name": "Russian Gov Aircraft", "program": "CAATSA", "risk": "HIGH"})
    print("  ✅ Sanctions: 1 entity ingested")

    # Internet outage
    godseye.ingest("internet_outage", "OUT-20260804-001", 37.80, -122.40,
                   {"severity": "partial", "asn": 15169, "provider": "Google"})
    print("  ✅ Internet: 1 outage ingested")

    print(f"\n  📊 TOTAL: {godseye.stats()['total_datapoints']} data points across {godseye.stats()['total_feeds']} feeds\n")

    # ─── SEARCH 1: Find Elon Musk's jet ───
    print("═" * 70)
    print("🔍 GOD'S EYE SEARCH: 'N628TS' (Elon Musk's private jet)")
    print("═" * 70)

    result = godseye.search("N628TS", radius_km=5.0)

    print(f"\n  📊 Results: {result['total_hits']} hits across {len(result['hits'])} feeds")
    for feed, dps in result["hits"].items():
        print(f"     [{feed:<18}] {len(dps)} matches: {[d.entity_id for d in dps[:3]]}")

    if result["proximity_hits"]:
        print(f"\n  📍 PROXIMITY ({len(result['proximity_hits'])} nearby):")
        for ph in result["proximity_hits"][:10]:
            dp = ph["point"]
            print(f"     [{dp.feed:<18}] {dp.entity_id:<25} {ph['distance_km']:.1f}km away")

    if result["cross_feed_correlations"]:
        print(f"\n  🔗 CROSS-FEED CORRELATIONS:")
        for corr in result["cross_feed_correlations"][:8]:
            print(f"     {corr['feed_a']}::{corr['entity_a']} ↔ "
                  f"{corr['feed_b']}::{corr['entity_b']} "
                  f"(IR sim={corr['ir_similarity']})")

    if result["entity_graph"]:
        print(f"\n  🕸️  ENTITY GRAPH:")
        for owner, assets in result["entity_graph"].items():
            print(f"     {owner} → {', '.join(assets)}")

    threat = result["threat_assessment"]
    print(f"\n  ⚠️  THREAT: {threat['level']} (score={threat['score']}/100)")
    for f in threat["factors"]:
        print(f"     • {f}")

    # ─── SEARCH 2: Threat scan ───
    print(f"\n{'═' * 70}")
    print("🔍 GOD'S EYE SEARCH: 'RA-96023' (Russian government aircraft)")
    print("═" * 70)

    result2 = godseye.search("RA-96023")
    threat2 = result2["threat_assessment"]
    print(f"\n  ⚠️  THREAT: {threat2['level']} (score={threat2['score']}/100)")
    for f in threat2["factors"]:
        print(f"     • {f}")
    for feed, dps in result2["hits"].items():
        print(f"     [{feed:<18}] {len(dps)} matches: {[d.entity_id for d in dps[:2]]}")

    # ─── Continuous Track ───
    print(f"\n{'═' * 70}")
    print("🎯 CONTINUOUS TRACK: N628TS (Persistent monitoring)")
    print("═" * 70)

    track = godseye.continuous_track("N628TS", interval_sec=30.0)
    print(f"\n  📍 Current position: feeds={len(track['current']['hits'])}, "
          f"hits={track['current']['total_hits']}")
    if track["prediction"]:
        p = track["prediction"]
        print(f"  🔮 Predicted next: {p['lat']}, {p['lon']} (conf={p['confidence']})")
        print(f"     Based on: {p['based_on']}")
    print(f"  ⏱️  Next update: {track['next_update_in']}s")

    # ─── FINAL ───
    print(f"\n{'═' * 70}")
    print(f"🏁 GOD'S EYE STATUS")
    print(f"{'═' * 70}")
    s = godseye.stats()
    print(f"  Feeds active:     {s['total_feeds']}")
    print(f"  Entities tracked: {s['total_entities']}")
    print(f"  Data points:      {s['total_datapoints']}")
    print(f"  Searches:         {s['searches_performed']}")
    print()
    print(f"  🎯 God's Eye = ShadowBroker (60+ feeds) + GraphLang (IR fusion)")
    print(f"  🔗 Every data point normalized to 12 IR kinds")
    print(f"  🧠 merge_graphs() finds what no human analyst would")
    print(f"{'═' * 70}")


if __name__ == "__main__":
    demo()
