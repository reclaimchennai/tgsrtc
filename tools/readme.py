#!/usr/bin/env python3
"""README.md for an RTC open-data repo, written from its data/stats.json.   readme.py --net apsrtc|tgsrtc --repo DIR"""
import argparse, json, os

LICENSE = """Open Data Commons Open Database License (ODbL) v1.0

The data in this repository is made available under the Open Database License:
https://opendatacommons.org/licenses/odbl/1-0/. Any rights in individual contents of
the database are licensed under the Database Contents License:
https://opendatacommons.org/licenses/dbcl/1-0/

Attribution: "reclaim.city — github.com/reclaimchennai/{net}", plus the upstream sources
named in README.md (the TGSRTC GTFS is Open Data Telangana's, published under its own terms).
"""


def fmt(n):
    return f'{n:,}' if isinstance(n, int) else str(n)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--net', required=True); ap.add_argument('--repo', required=True)
    a = ap.parse_args(); net = a.net; NET = net.upper()
    st = json.load(open(os.path.join(a.repo, 'data', 'stats.json')))
    shots = sorted(os.listdir(os.path.join(a.repo, 'screenshots')))
    img = lambda n, alt: f'![{alt}](screenshots/{n})' if n in shots else ''
    if net == 'apsrtc':
        head = f"""# APSRTC — open bus data for Andhra Pradesh

![GTFS](https://img.shields.io/badge/GTFS-static-blue) ![Routes](https://img.shields.io/badge/routes-{st['routes']}-green) ![Trips](https://img.shields.io/badge/trips%2Fday-{st['trips']}-green) ![License: ODbL](https://img.shields.io/badge/License-ODbL-red)

Every APSRTC (Andhra Pradesh State Road Transport Corporation) service we have seen, as one
GTFS feed, with how late each one usually runs. Collected by **reclaim.city** for the live map at
**[maps.reclaim.city/apsrtc](https://maps.reclaim.city/apsrtc/)**. APSRTC publishes no GTFS of its own.

{img('network.png', 'APSRTC network')}

## What's in it

| File | What | Size |
|---|---|---|
| [`data/apsrtc-gtfs.zip`](data/apsrtc-gtfs.zip) | **The GTFS feed** — agency, routes, trips, stops, stop_times, shapes, calendar, feed_info | {fmt(st['routes'])} routes · {fmt(st['trips'])} trips · {fmt(st['stops'])} stops · {fmt(st['stop_times'])} stop times · {fmt(st['shapes'])} shapes |
| `data/gtfs/` | the small GTFS files unzipped, to browse | |
| [`data/stop_delays.csv.gz`](data/stop_delays.csv.gz) | per trip and stop: the **median lateness** over a week of the bus's own GPS (minutes) | {fmt(st['stop_delays'])} rows |
| [`data/punctuality/`](data/punctuality/) | per service day (`YYYY-MM-DD.csv.gz`) and stop: scheduled time, GPS arrival and departure, delay, dwell, skipped | {fmt(st['punctuality_rows'])} rows, {len(st.get('punctuality_days', []))} days |
| [`data/service_days.csv.gz`](data/service_days.csv.gz) | per service and day: the bus that ran it, depot, service type, start/end delay, GPS fixes | {fmt(st['service_days'])} rows ({' to '.join(st['days'][:1] + st['days'][-1:]) if st['days'] else '—'}) |
| [`data/stats/`](data/stats/) | `punctuality_by_depot.csv`, `punctuality_by_type.csv` (median and 80th-percentile delay at the last stop, % on time −2…+5 min), `coverage.csv` (services, buses and depots per day), `fleet_by_depot.csv` (buses and services by depot and type) | |
| `data/web/` | the live map's own network files (stops, services with timetables and delays, road segments) | |
| [`data/drivers/`](data/drivers/) | **driver working hours**: `driver_hours.csv.gz` per pseudonymous driver and day, `depot_hours.csv` per depot and day — see below | |
| [`data/realtime/`](data/realtime/) | **GTFS-Realtime** samples: VehiclePositions and TripUpdates (`.pb`, and `.json.gz` to read) — see below | |
| `data/stats.json` | the numbers on this page | |
| `tools/` | how this repo is built from the collected data (`build_apsrtc.py`, `charts.py`, `readme.py`); the collectors are not published | |

### How it is built

- **Stops** are APSRTC's own place ids (`placeId`), the same ids the APSRTC Live Track app uses.
- **Trips** are APSRTC services (`<duty>_<trip>_<DEPOT>`, a service that repeats every day), each with its
  stop list and timetable as the app publishes them. `trip_short_name` is APSRTC's service number.
- **Routes** are corridors, as on the map: every service between the same two termini, city services
  (City Ordinary, Metro Express, Metro Luxury) kept apart from intercity ones. `route_id` is the map's
  route address (`maps.reclaim.city/apsrtc/?route=<route_id>`); `route_short_name` is the most common
  route code on the corridor. APSRTC has no public route numbers.
- **Shapes** follow the road between consecutive stops: OSRM on OpenStreetMap, or where OSRM has no road,
  the path buses actually drove (from their GPS).
- **De-duplicated**: one trip per service; the Neo2308 community GTFS (Aug 2026) is merged only where it
  has a service we do not ({fmt(st['trips_from_neo2308'])} trips, route ids `neo-…`).
- No driver data is in this repository, and none was ever collected into it.
"""
        src = """## Sources

| What | Source |
|---|---|
| services, stops, timetables, GPS | the public **APSRTC Live Track** app (apsrtclivetrack.com), collected by reclaim.city |
| roads | OpenStreetMap, routed with OSRM |
| extra services | [Neo2308's APSRTC GTFS](https://github.com/Neo2308) (Aug 2026) |

### Limitations

- Unofficial: built from what the public app shows; APSRTC may change or withdraw services at any time.
- One calendar (`daily`): the app lists today's services; services that do not run every day are not told apart yet.
- Times are the timetable. How late a service actually runs is in `stop_delays.csv.gz` and `punctuality.csv.gz`.
"""
    else:
        o, c = st['official'], st['combined']
        head = f"""# TGSRTC — open bus data for Telangana

![GTFS](https://img.shields.io/badge/GTFS-static-blue) ![Trips](https://img.shields.io/badge/trips-{c.get('trips.txt', 0)}-green) ![Added](https://img.shields.io/badge/collected%20trips-{st['added_trips']}-orange) ![License: ODbL](https://img.shields.io/badge/License-ODbL-red)

The official TGSRTC GTFS (Open Data Telangana) **joined with every service we have collected that it
does not carry** — mostly district and intercity buses — plus what the buses actually did. Collected by
**reclaim.city** for the live map at **[maps.reclaim.city/tgsrtc](https://maps.reclaim.city/tgsrtc/)**.

{img('network.png', 'TGSRTC network')}

## What's in it

| File | What | Size |
|---|---|---|
| [`data/tgsrtc-gtfs.zip`](data/tgsrtc-gtfs.zip) | **The combined GTFS feed** | {fmt(c.get('routes.txt', 0))} routes · {fmt(c.get('trips.txt', 0))} trips · {fmt(c.get('stops.txt', 0))} stops · {fmt(c.get('stop_times.txt', 0))} stop times |
| `data/gtfs/` | the small GTFS files unzipped, to browse (stop_times and shapes are in the zip) | |
| [`data/trip_observations.csv.gz`](data/trip_observations.csv.gz) | per collected service-day and stop: **planned, arrived and left** (IST), route, service type, depot, bus | {fmt(st['observation_rows'])} rows |
| [`data/stats/`](data/stats/) | `punctuality_by_route.csv`, `punctuality_by_depot.csv` (median and 80th-percentile delay, % on time −2…+5 min, origin excluded), `coverage.csv` (trips, services, buses, routes, depots, stops logged per day) | |
| `data/web/` | the live map's own network files (stops, services, road segments) | |
| [`data/drivers/`](data/drivers/) | **driver working hours**: `driver_hours.csv.gz` per pseudonymous driver and day, `depot_hours.csv` per depot and day — see below | |
| [`data/realtime/`](data/realtime/) | **GTFS-Realtime** samples: VehiclePositions and TripUpdates (`.pb`, and `.json.gz` to read) — see below | |
| `data/stats.json` | the numbers on this page | |
| `tools/` | how this repo is built (`build_tgsrtc.py`, `charts.py`, `readme.py`); the collectors are not published | |

### How it is built

- **The official feed is kept as published** ({fmt(o['routes'])} route numbers, {fmt(o['stops'])} stops, Hyderabad city).
- **Collected services are added** when their route number is not in the official feed: {fmt(st['added_routes'])} routes,
  {fmt(st['added_trips'])} trips, {fmt(st['added_stops'])} new stops (ids prefixed `tgc-`), from the TGSRTC Bus Tracking service:
  each trip's stops with planned times and the bus's GPS line as its shape.
- **Stops are shared**: a collected stop within 100 m of an official stop with the same name uses the official `stop_id`.
- **De-duplicated**: one trip per service (its most complete record). The {fmt(st['collected_in_official'])} collected services already in the
  official feed are not added again; what those buses did is kept in `trip_observations.csv.gz`.
- No driver data is in this repository, and none was ever collected into it.
"""
        src = """## Sources

| What | Source |
|---|---|
| city routes, stops, timetables, shapes | [Open Data Telangana](https://data.telangana.gov.in/) — TGSRTC GTFS, 25 Sep 2026 |
| district services, observed times | the public **TGSRTC Bus Tracking** service, collected by reclaim.city |
| roads (map segments) | OpenStreetMap, routed with OSRM |

### Limitations

- Collected services are added from the days they were seen running; one calendar (`daily`) is used for them.
- Planned times for collected services are TGSRTC's own; observed times are in `trip_observations.csv.gz`.
"""
    gallery = '\n\n'.join(x for x in [img('departures.png', 'Departures by hour'), img('service-types.png', 'Trips by kind of bus'),
                                       img('delays.png', 'How late the buses run')] + [img(n, n[:-4]) for n in shots if n.startswith('map-')] if x)
    rt = json.load(open(os.path.join(a.repo, 'data', 'realtime', 'status.json'))) if os.path.exists(os.path.join(a.repo, 'data', 'realtime', 'status.json')) else None
    how = ("a live bus id is `<ddmmyyyy>_<trip_id>`, so every bus on a published service carries its exact `trip_id` and `start_date`; "
           "stop times ahead are the timetable plus how late the bus is running now (it has not reached its next stop and that stop's time has passed)"
           if net == 'apsrtc' else
           "each bus's route number and service come from the TGSRTC tracking feed; collected district services are trip `tgc-<serviceId>`, and on official city routes "
           "the trip is the one whose timetable is nearest (within 3 min, and alone that near) to the bus's planned time at the same stop — otherwise the bus carries its "
           "`route_id` only; stop times ahead are our nowcast model's predicted arrivals")
    rtsec = (f"""## GTFS-Realtime

Standard **GTFS-RT 2.0** Protocol Buffer feeds, built from the same live data as the map, with ids that match the
static GTFS above: **VehiclePositions** (every live bus: position, bearing, speed, vehicle number, and its trip and
route where known) and **TripUpdates** (arrival time and delay at each stop still ahead).

| Feed | Sample in this repo | Snapshot |
|---|---|---|
| VehiclePositions | [`data/realtime/vehicle_positions.pb`](data/realtime/vehicle_positions.pb) (+ `.json.gz`) | {fmt(rt['vehicles'])} buses, {fmt(rt['on_trip'])} on a known GTFS trip |
| TripUpdates | [`data/realtime/trip_updates.pb`](data/realtime/trip_updates.pb) (+ `.json.gz`) | {fmt(rt['trip_updates'])} trips |

How trips are matched: {how}. The generator is [`tools/gtfs_rt.py`](tools/gtfs_rt.py)
(`gtfs_rt.py index {net} {net}-gtfs.zip rt_index.json`, then `gtfs_rt.py serve …`); the samples are one snapshot.
Live feeds, refreshed every 30 s, are being switched on at `https://maps.reclaim.city/{net}/rt/vehicle_positions.pb`
and `…/trip_updates.pb`.

""" if rt else '')
    dh = os.path.join(a.repo, 'data', 'drivers', 'depot_hours.csv')
    drv = ''
    if os.path.exists(dh):
        import csv as _csv
        rows = list(_csv.DictReader(open(dh)))
        nd = sum(int(r['drivers']) for r in rows); o8 = sum(int(r['drivers_over_8h_planned']) for r in rows); o10 = sum(int(r['drivers_over_10h_planned']) for r in rows)
        drv = f"""## Driver working hours

How long TGSRTC drivers work, from the trips they drove ({rows[0]['date']} onwards, {len(rows)} depot-days, {fmt(nd)} driver-days counted):
**{fmt(o8)}** driver-days planned over 8 hours of driving, **{fmt(o10)}** over 10.

- [`data/drivers/driver_hours.csv.gz`](data/drivers/driver_hours.csv.gz) — per driver and day: depot, routes, service type, trips, buses,
  planned and observed first and last hour, span and driving hours, and `reliable`.
- [`data/drivers/depot_hours.csv`](data/drivers/depot_hours.csv) — per depot and day: drivers, trips, median and 90th-percentile planned and
  observed driving hours, drivers over 8 h and 10 h, and how many rows were left out or marked unreliable.

**Privacy.** No names, phone numbers, staff or licence numbers are in this repository. Each driver is a pseudonym
(`d-xxxx-xxxx-xxxx-xxxx`): a keyed hash (HMAC-SHA256) of an internal id that is itself a salted hash of the driver's name and
mobile number; the key and salt are never published, so a pseudonym cannot be traced back to a person, and it stays the same
from day to day. Times are rounded to the hour and hours to the quarter hour, so a row cannot be matched to a particular bus run.

**Read with care.** Hours are lower bounds (a short trip between two reads of the tracking feed can be missed). `id_basis` says
how sure the id is: `name+mobile` is one person; `name` may merge two drivers of the same name at a depot. Rows where an id was on
two buses at once (two drivers sharing a name) and placeholder "names" (a depot, route or bus type typed in the name field) are left
out. Days no one person works (a span over 16 h, or more than 3 buses) are kept but marked `reliable = 0`, and are not in the depot totals.

"""
    use = rtsec + drv + f"""## Use it

```bash
curl -LO https://github.com/reclaimchennai/{net}/raw/main/data/{net}-gtfs.zip
```

Load it into OpenTripPlanner, `gtfs-kit` / `partridge` (Python), `tidytransit` (R), or any GTFS tool.

## See it live

[maps.reclaim.city/{net}](https://maps.reclaim.city/{net}/) — every route and every live {NET} bus, the next bus
at every stop, timetables and how late they usually run.

## Statistics

{gallery}

## Licence

Data: [ODbL 1.0](LICENSE). Please credit **reclaim.city** and the sources above.
"""
    open(os.path.join(a.repo, 'README.md'), 'w').write(head + '\n' + use + '\n' + src)
    open(os.path.join(a.repo, 'LICENSE'), 'w').write(LICENSE.format(net=net))
    print('README', len(open(os.path.join(a.repo, 'README.md')).read()), 'chars')


if __name__ == '__main__':
    main()
