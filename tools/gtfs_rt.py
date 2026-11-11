#!/usr/bin/env python3
"""GTFS-Realtime feeds for the bus maps (APSRTC, TGSRTC, Delhi), from the maps' own live data.

    gtfs_rt.py index apsrtc|tgsrtc GTFS_ZIP OUT.json   build the trip index (rt_index.json) from the published GTFS
    gtfs_rt.py serve --net apsrtc|tgsrtc|delhi --live URL-or-DIR --data DIR --out DIR [--every 15]

Each cycle checks the source and rewrites the feeds only when it has changed; the feed
header's timestamp is the source's own time (when its newest positions were read).

Every `--every` seconds, writes to OUT (served at maps.reclaim.city/<net>/rt/):
  vehicle_positions.pb   GTFS-RT FeedMessage: every live bus, its position, bearing, speed and,
                         where known, its GTFS trip (trip_id, start_date) and route
  trip_updates.pb        GTFS-RT FeedMessage: for buses on a known trip, the arrival time and
                         delay at each stop still ahead
  *.json                 the same feeds as JSON, for people reading them by eye
The trip_ids are the ones in the published static GTFS (github.com/reclaimchennai/<net>):
  APSRTC  a live bus id is <ddmmyyyy>_<service key>; the service key is the GTFS trip_id. Stop
          times ahead: the timetable plus how late the bus is now (it has not reached its next
          stop and that stop's time has passed).
  TGSRTC  live/routelink.json gives each bus its route number and serviceId. Collected district
          services are GTFS trip `tgc-<serviceId>`; on official city routes the trip is the one
          whose timetable is nearest (within 3 min, and alone that near) to the bus's planned time
          (live/etas.json) at the same stop; otherwise the bus carries its route_id only. Stop times
          ahead: our nowcast model's predicted arrivals (live/etas.json).
  Delhi   live/vehicles.json rows [registration, route code, lat, lon, bearing, fix, flags,
          [stop index, seconds after the fix, ...]]: the route code is the Delhi GTFS route_id the map
          uses (data/route_stops.json), and stop times ahead are the map's predicted arrivals at that
          route's stops (stop_id = the GTFS stop_id).
No driver data is read or written."""
import argparse, csv, datetime as dt, gzip, io, json, math, os, re, sys, time, urllib.request, zipfile

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
place = lambda n: re.sub(r'\s+twd\b.*$', '', str(n or ''), flags=re.I).strip()
nkey = lambda n: re.sub(r'[^A-Z0-9]', '', place(n).upper())
rkey = lambda n: str(n or '').strip().upper().replace(' ', '')


def hav(a, b):
    return math.hypot((a[0] - b[0]) * 111320 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111320)


# ── TGSRTC index, built once from the published GTFS ──
def build_index_apsrtc(zp, out):
    """trip_id -> [route_id, [[stop_sequence, stop_id, minute of day]]], stop_id -> [lat, lon], from the published GTFS."""
    z = zipfile.ZipFile(zp)
    rd = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), encoding='utf-8-sig'))
    stops = {r['stop_id']: [round(float(r['stop_lat']), 6), round(float(r['stop_lon']), 6)] for r in rd('stops.txt')}
    trips = {r['trip_id']: [r['route_id'], []] for r in rd('trips.txt')}
    for r in rd('stop_times.txt'):
        t = r['arrival_time'] or r['departure_time']
        trips[r['trip_id']][1].append([int(r['stop_sequence']), r['stop_id'], int(t[:2]) * 60 + int(t[3:5]) if t else None])
    for v in trips.values():
        v[1].sort()
    json.dump({'trips': trips, 'stops': stops}, open(out, 'w'), separators=(',', ':'))
    print(f'index: {len(trips)} trips, {len(stops)} stops -> {out} ({os.path.getsize(out) // 1024} KB)')


def build_index(zp, out):
    z = zipfile.ZipFile(zp)
    rd = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), encoding='utf-8-sig'))
    sname = {r['stop_id']: nkey(r['stop_name']) for r in rd('stops.txt')}
    routes = {r['route_id']: r['route_short_name'] for r in rd('routes.txt')}
    trips = {r['trip_id']: r['route_id'] for r in rd('trips.txt')}
    seqs = {}
    for r in rd('stop_times.txt'):
        t = r['arrival_time'] or r['departure_time']
        m = int(t[:2]) * 60 + int(t[3:5]) if t else None
        seqs.setdefault(r['trip_id'], []).append((int(r['stop_sequence']), r['stop_id'], m))
    tgc, official, rnum = {}, {}, {}
    for rid, num in sorted(routes.items(), key=lambda x: x[0].startswith('tgc-')):   # official route ids first
        rnum.setdefault(rkey(num), rid)
    for tid, ss in seqs.items():
        ss.sort()
        rid = trips.get(tid)
        if tid.startswith('tgc-'):
            tgc[tid] = [rid, [[q, s, sname.get(s, '')] for q, s, _ in ss]]
        else:
            # per route, per stop name: (minute of day, trip, sequence, stop) — to find the trip a bus is on
            o = official.setdefault(rid, {})
            for q, s, m in ss:
                if m is not None:
                    o.setdefault(sname.get(s, ''), []).append([m % 1440, tid, q, s])
    json.dump({'tgc': tgc, 'official': official, 'rnum': rnum}, open(out, 'w'), separators=(',', ':'))
    print(f'index: {len(tgc)} collected trips, {len(official)} official routes -> {out} ({os.path.getsize(out) // 1024} KB)')


# ── feeds ──
def get(url):
    if not url.startswith('http'):                       # a local file (the Delhi collector writes on this host)
        return json.load(open(url))
    req = urllib.request.Request(url, headers={'User-Agent': 'reclaim.city-gtfs-rt/1 (+https://maps.reclaim.city)'})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def feed(pb, entities, now, src_t=None):
    m = pb.FeedMessage()
    m.header.gtfs_realtime_version = '2.0'
    m.header.incrementality = pb.FeedHeader.FULL_DATASET
    m.header.timestamp = int(src_t or now)
    for e in entities:
        m.entity.append(e)
    return m


def write(out, name, msg):
    from google.protobuf import json_format
    for ext, data in (('pb', msg.SerializeToString()), ('json', json_format.MessageToJson(msg, indent=None).encode())):
        p = os.path.join(out, f'{name}.{ext}'); tmp = p + '.tmp'
        open(tmp, 'wb').write(data); os.replace(tmp, p)


def vehicle(pb, eid, b, trip_id=None, route_id=None, start_date=None):
    e = pb.FeedEntity(); e.id = eid
    v = e.vehicle
    if trip_id: v.trip.trip_id = trip_id
    if route_id: v.trip.route_id = route_id
    if start_date: v.trip.start_date = start_date
    v.position.latitude = float(b['lat']); v.position.longitude = float(b['lon'])
    if b.get('brg') is not None: v.position.bearing = float(b['brg'])
    if b.get('spd') is not None: v.position.speed = float(b['spd']) / 3.6        # km/h -> m/s
    v.timestamp = int(b['t'])
    v.vehicle.id = str(b['id']); v.vehicle.label = str(b.get('veh') or ''); v.vehicle.license_plate = str(b.get('veh') or '')
    return e


def update(pb, eid, b, trip_id, route_id, start_date, stus, now):
    e = pb.FeedEntity(); e.id = eid
    u = e.trip_update
    u.trip.trip_id = trip_id
    if route_id: u.trip.route_id = route_id
    if start_date: u.trip.start_date = start_date
    u.vehicle.id = str(b['id']); u.vehicle.label = str(b.get('veh') or '')
    u.timestamp = int(b['t'])
    for seq, stop_id, at, delay in stus:
        s = u.stop_time_update.add()
        if seq is not None: s.stop_sequence = seq
        if stop_id: s.stop_id = stop_id
        s.arrival.time = int(at)
        if delay is not None: s.arrival.delay = int(delay)
    return e


def apsrtc_cycle(pb, a, S):
    v = get(a.live.rstrip('/') + '/vehicles.json'); now = time.time()
    c = {k: i for i, k in enumerate(v['cols'])}
    trips, stops = S['trips'], S['stops']
    VP, TU = [], []
    for row in v['buses']:
        b = {k: row[i] for k, i in c.items()}
        bid = str(b['id'])
        key = bid.split('_', 1)[1] if '_' in bid else ''
        d8 = bid[:8]
        sdate = d8[4:8] + d8[2:4] + d8[0:2] if d8.isdigit() else None
        tr = trips.get(key)
        if not tr:
            VP.append(vehicle(pb, bid, b)); continue
        route_id, ss = tr
        VP.append(vehicle(pb, bid, b, key, route_id, sdate))
        timed = [x for x in ss if x[2] is not None]
        if not timed or not sdate:
            continue
        m0 = timed[0][2]
        at = lambda m: m + 1440 if m < m0 - 60 else m
        pos = (float(b['lon']), float(b['lat']))
        # the stop the bus is heading for: the nearest stop, or the one after it if the bus is past it
        bi, bd = 0, 1e18
        for i, (q, sid, m) in enumerate(ss):
            x = stops.get(sid)
            if x:
                dd = hav((x[1], x[0]), pos)
                if dd < bd: bd, bi = dd, i
        n = bi
        if bi + 1 < len(ss):
            x, y = stops.get(ss[bi][1]), stops.get(ss[bi + 1][1])
            if x and y and hav((y[1], y[0]), pos) < hav((x[1], x[0]), (y[1], y[0])): n = bi + 1
        base = dt.datetime.strptime(sdate, '%Y%m%d').replace(tzinfo=IST).timestamp()
        nowm = (now - base) / 60
        nm = next((at(x[2]) for x in ss[n:] if x[2] is not None), None)
        late = max(0.0, nowm - nm) if nm is not None else 0.0
        if late > 180:                       # three hours late is a wrong match (a stale service), not a delay
            continue
        stus = [(q, sid, max(base + (at(m) + late) * 60, now), int(late * 60)) for q, sid, m in ss[n:] if m is not None]
        if stus:
            TU.append(update(pb, 'tu-' + bid, b, key, route_id, sdate, stus, now))
    return VP, TU, now


def tgsrtc_cycle(pb, a, S):
    base = a.live.rstrip('/')
    v = get(base + '/vehicles.json'); rl = get(base + '/routelink.json'); et = get(base + '/etas.json').get('buses', {}); now = time.time()
    c = {k: i for i, k in enumerate(v['cols'])}
    tgc, official, rnum = S['tgc'], S['official'], S['rnum']
    VP, TU = [], []
    for row in v['buses']:
        b = {k: row[i] for k, i in c.items()}
        bid = str(b['id']); L = rl.get(bid); E = et.get(bid)
        trip_id = route_id = sdate = None
        if L:
            tid = f'tgc-{L[1]}'
            if tid in tgc:
                trip_id, route_id = tid, tgc[tid][0]
            else:
                route_id = rnum.get(rkey(L[0]))
                # the official trip whose timetable has the bus's planned time at the same stop
                if route_id and E and E[4]:
                    o = official.get(route_id, {})
                    for name, eta, plan in E[4][:3]:
                        if not plan: continue
                        pm = int((plan - dt.datetime.fromtimestamp(plan, IST).replace(hour=0, minute=0, second=0).timestamp()) // 60)
                        # the nearest timetabled trip within 3 min, if it is the only one that near
                        near = sorted((abs(x[0] - pm), x[1]) for x in o.get(nkey(name), []) if abs(x[0] - pm) <= 3)
                        if near and (len(near) == 1 or near[1][0] > near[0][0]):
                            trip_id = near[0][1]; break
        if E and E[4] and E[4][0][2]:
            sdate = dt.datetime.fromtimestamp(E[4][0][2], IST).strftime('%Y%m%d')
        VP.append(vehicle(pb, bid, b, trip_id, route_id, sdate if trip_id else None))
        if trip_id and E and E[4]:
            stus = []
            if trip_id in tgc:
                byname = {}
                for q, sid, nk in tgc[trip_id][1]:
                    byname.setdefault(nk, (q, sid))
                for name, eta, plan in E[4]:
                    q = byname.get(nkey(name))
                    if q and eta: stus.append((q[0], q[1], eta, (eta - plan) if plan else None))
            else:
                o = official.get(route_id, {})
                for name, eta, plan in E[4]:
                    hit = [x for x in o.get(nkey(name), []) if x[1] == trip_id]
                    if hit and eta: stus.append((hit[0][2], hit[0][3], eta, (eta - plan) if plan else None))
            stus.sort()
            if stus:
                TU.append(update(pb, 'tu-' + bid, b, trip_id, route_id, sdate, stus, now))
    return VP, TU, now


def delhi_cycle(pb, a, S):
    j = get(a.live.rstrip('/') + '/vehicles.json'); now = time.time()
    rs = S['routes']
    VP, TU = [], []
    for v in j['v']:
        reg, code, lat, lon, brg, fix, fl = v[:7]
        eta = v[7] if len(v) > 7 else []
        b = {'id': reg, 'veh': reg, 'lat': lat, 'lon': lon, 'brg': brg, 'spd': None, 't': fix}
        st = rs.get(code)
        VP.append(vehicle(pb, reg, b, None, code if st else None, None))
        if not st or not eta:
            continue
        stus = []
        if eta and isinstance(eta[0], list):                 # older files: [[i, etaEpoch], ...]
            pairs = [(i, t) for i, t in eta]
        else:
            pairs = [(eta[k], fix + eta[k + 1]) for k in range(0, len(eta) - 1, 2)]
        for i, t in pairs:
            if 0 <= i < len(st) and t >= now - 60:
                stus.append((i + 1, st[i], t, None))
        if stus:
            e = pb.FeedEntity(); e.id = 'tu-' + reg
            u = e.trip_update; u.trip.route_id = code
            u.vehicle.id = reg; u.vehicle.label = reg; u.timestamp = int(fix)
            for q, sid, t, _ in stus:
                x = u.stop_time_update.add(); x.stop_sequence = q; x.stop_id = sid; x.arrival.time = int(t)
            TU.append(e)
    return VP, TU, now


def serve(a):
    from google.transit import gtfs_realtime_pb2 as pb
    os.makedirs(a.out, exist_ok=True)
    if a.net == 'apsrtc':
        S = json.load(open(os.path.join(a.data, 'rt_index.json')))
        cycle = apsrtc_cycle
    elif a.net == 'delhi':
        r = json.load(open(os.path.join(a.data, 'route_stops.json')))
        S = {'routes': {code: [x[0] for x in v['d'][0]['s']] for code, v in r.items() if v.get('d')}}
        cycle = delhi_cycle
    else:
        S = json.load(open(os.path.join(a.data, 'rt_index.json')))
        cycle = tgsrtc_cycle
    src = a.live.rstrip('/') + '/vehicles.json'
    last = None
    while True:
        t0 = time.time()
        try:
            # cheap change check first: the source's own timestamp (or the file's mtime)
            stamp = os.path.getmtime(src) if not src.startswith('http') else None
            if stamp is None or stamp != last:
                VP, TU, now = cycle(pb, a, S)
                # the newest fix, never ahead of now (one bus with a fast clock must not date the feed)
                src_t = min(int(now), max((e.vehicle.timestamp for e in VP if e.vehicle.timestamp <= now + 60), default=int(now)))
                if src_t != last or stamp is not None:
                    write(a.out, 'vehicle_positions', feed(pb, VP, now, src_t))
                    write(a.out, 'trip_updates', feed(pb, TU, now, src_t))
                    tmp = os.path.join(a.out, 'status.json.tmp')
                    json.dump({'network': a.net, 'feed_time': int(src_t), 'written': int(now), 'vehicles': len(VP),
                               'on_trip': sum(1 for e in VP if e.vehicle.trip.trip_id), 'on_route': sum(1 for e in VP if e.vehicle.trip.route_id),
                               'trip_updates': len(TU)}, open(tmp, 'w'))
                    os.replace(tmp, os.path.join(a.out, 'status.json'))
                    print(time.strftime('%H:%M:%S'), a.net, len(VP), 'vehicles', len(TU), 'trip updates', flush=True)
                last = stamp if stamp is not None else src_t
        except Exception as e:
            # the last good feed stays up; a failed cycle never overwrites it
            print('cycle failed:', type(e).__name__, e, flush=True)
        time.sleep(max(2, a.every - (time.time() - t0)))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'index':
        return (build_index_apsrtc if sys.argv[2] == 'apsrtc' else build_index)(sys.argv[3], sys.argv[4])
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd'); ap.add_argument('--net', required=True); ap.add_argument('--live', required=True)
    ap.add_argument('--data', required=True); ap.add_argument('--out', required=True); ap.add_argument('--every', type=int, default=15)
    ap.add_argument('--once', action='store_true')
    a = ap.parse_args()
    if a.once:
        from google.transit import gtfs_realtime_pb2 as pb
        a.every = 0
    serve(a)


if __name__ == '__main__':
    main()
