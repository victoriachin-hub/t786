#!/usr/bin/env python3
"""
T786 bus tracker — polls Malaysia's open GTFS-Realtime feed for RapidKL buses,
finds vehicles running route T786, and logs their distance/ETA to the
"Jaya One Mall (Opp)" stop into a running CSV history file.

Designed to be run on a schedule (e.g. every 2 minutes via GitHub Actions)
during the hours you care about. Each run is a single poll + log; history
accumulates across runs because the CSV is committed back to the repo.

Data source: https://developer.data.gov.my/realtime-api/gtfs-realtime
"""

import csv
import io
import os
import zipfile
from datetime import datetime, timezone, timedelta
from math import radians, sin, cos, sqrt, atan2

import requests
from google.transit import gtfs_realtime_pb2

# ---- Config ----------------------------------------------------------------

ROUTE_SHORT_NAME = "T786"
TARGET_STOP_NAME_HINTS = ["jaya one"]  # case-insensitive substring match on stop_name
MYT = timezone(timedelta(hours=8))  # Malaysia Time, UTC+8

GTFS_RT_URL = "https://api.data.gov.my/gtfs-realtime/vehicle-position/prasarana?category=rapid-bus-kl"
GTFS_STATIC_URL = "https://api.data.gov.my/gtfs-static/prasarana?category=rapid-bus-kl"

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATIC_CACHE_DIR = os.path.join(DATA_DIR, "static_cache")
HISTORY_CSV = os.path.join(DATA_DIR, "t786_history.csv")

os.makedirs(STATIC_CACHE_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in metres between two lat/lon points."""
    R = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def load_static_gtfs():
    """
    Download (or reuse a same-day cached copy of) the static GTFS zip,
    and extract routes.txt, trips.txt, stops.txt, stop_times.txt into memory.
    Static data only changes ~daily, so we cache it by date to avoid
    re-downloading the (largish) zip on every 2-minute poll.
    """
    today_str = datetime.now(MYT).strftime("%Y-%m-%d")
    cache_path = os.path.join(STATIC_CACHE_DIR, f"gtfs_{today_str}.zip")

    if not os.path.exists(cache_path):
        # Clean up old cached zips so the repo doesn't accumulate junk
        for f in os.listdir(STATIC_CACHE_DIR):
            try:
                os.remove(os.path.join(STATIC_CACHE_DIR, f))
            except OSError:
                pass
        resp = requests.get(GTFS_STATIC_URL, timeout=60)
        resp.raise_for_status()
        with open(cache_path, "wb") as f:
            f.write(resp.content)

    with open(cache_path, "rb") as f:
        zdata = f.read()

    zf = zipfile.ZipFile(io.BytesIO(zdata))

    def read_csv(name):
        with zf.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig")
            return list(csv.DictReader(text))

    routes = read_csv("routes.txt")
    trips = read_csv("trips.txt")
    stops = read_csv("stops.txt")
    stop_times = read_csv("stop_times.txt")

    return routes, trips, stops, stop_times


def find_target_route_ids(routes):
    """Find route_id(s) whose short name matches T786 (case-insensitive)."""
    matches = []
    for r in routes:
        short = (r.get("route_short_name") or "").strip().upper()
        if short == ROUTE_SHORT_NAME.upper():
            matches.append(r["route_id"])
    return matches


def find_target_stop_ids(stops):
    """Find stop_id(s) whose stop_name contains 'jaya one' (case-insensitive)."""
    matches = []
    for s in stops:
        name = (s.get("stop_name") or "").lower()
        if any(hint in name for hint in TARGET_STOP_NAME_HINTS):
            matches.append(s["stop_id"])
    return matches


def build_trip_to_stop_sequence(trips, stop_times, route_ids, target_stop_ids):
    """
    For every trip on our target route(s), find:
      - the full ordered list of stop_ids (for sequence-based distance/ETA)
      - which stop_sequence number corresponds to our target stop ("Jaya One")
    Returns: dict trip_id -> {"stops": [(seq, stop_id), ...], "target_seq": int or None}
    """
    trip_ids_on_route = {t["trip_id"] for t in trips if t["route_id"] in route_ids}

    trip_stop_map = {}
    for row in stop_times:
        tid = row["trip_id"]
        if tid not in trip_ids_on_route:
            continue
        trip_stop_map.setdefault(tid, []).append(
            (int(row["stop_sequence"]), row["stop_id"])
        )

    result = {}
    for tid, seq_list in trip_stop_map.items():
        seq_list.sort(key=lambda x: x[0])
        target_seq = None
        for seq, sid in seq_list:
            if sid in target_stop_ids:
                target_seq = seq
                break
        result[tid] = {"stops": seq_list, "target_seq": target_seq}
    return result


def build_stop_coords(stops):
    return {s["stop_id"]: (float(s["stop_lat"]), float(s["stop_lon"])) for s in stops}


def fetch_vehicle_positions():
    resp = requests.get(GTFS_RT_URL, timeout=30)
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


def ensure_csv_header():
    if not os.path.exists(HISTORY_CSV):
        with open(HISTORY_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "poll_timestamp_myt",
                "date",
                "time",
                "vehicle_id",
                "trip_id",
                "route_id",
                "current_stop_seq",
                "target_stop_seq",
                "stops_remaining_to_jaya_one",
                "straight_line_distance_m",
                "vehicle_lat",
                "vehicle_lon",
            ])


def main():
    now = datetime.now(MYT)
    print(f"[{now.isoformat()}] Polling T786 realtime feed...")

    routes, trips, stops, stop_times = load_static_gtfs()
    route_ids = find_target_route_ids(routes)
    if not route_ids:
        print("WARNING: No route found matching T786 in static GTFS. Aborting this run.")
        return
    target_stop_ids = find_target_stop_ids(stops)
    if not target_stop_ids:
        print("WARNING: No stop found matching 'Jaya One'. Aborting this run.")
        return

    print(f"  Matched route_id(s): {route_ids}")
    print(f"  Matched target stop_id(s): {target_stop_ids}")

    trip_info = build_trip_to_stop_sequence(trips, stop_times, route_ids, target_stop_ids)
    stop_coords = build_stop_coords(stops)
    jaya_one_lat, jaya_one_lon = stop_coords[target_stop_ids[0]]

    feed = fetch_vehicle_positions()

    ensure_csv_header()
    rows_to_write = []

    found_any = False
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        trip_id = v.trip.trip_id if v.HasField("trip") else None
        if not trip_id or trip_id not in trip_info:
            continue

        found_any = True
        info = trip_info[trip_id]
        target_seq = info["target_seq"]

        current_seq = v.current_stop_sequence if v.HasField("current_stop_sequence") else None

        stops_remaining = None
        if target_seq is not None and current_seq is not None:
            stops_remaining = target_seq - current_seq

        lat = v.position.latitude if v.HasField("position") else None
        lon = v.position.longitude if v.HasField("position") else None
        dist_m = None
        if lat is not None and lon is not None:
            dist_m = round(haversine_m(lat, lon, jaya_one_lat, jaya_one_lon), 1)

        rows_to_write.append([
            now.isoformat(),
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            v.vehicle.id if v.HasField("vehicle") else "",
            trip_id,
            v.trip.route_id if v.HasField("trip") else "",
            current_seq,
            target_seq,
            stops_remaining,
            dist_m,
            lat,
            lon,
        ])

    if not found_any:
        # Still worth a log line (not a CSV row) so Action logs show "no bus running right now"
        print("  No T786 vehicles currently reporting position (may be between trips / off-hours).")
        return

    with open(HISTORY_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows_to_write)

    print(f"  Logged {len(rows_to_write)} T786 vehicle observation(s).")


if __name__ == "__main__":
    main()
