#!/usr/bin/env python3
"""TGSRTC open data: the official GTFS joined with every service we have collected that it lacks.

    build_tgsrtc.py --gtfs DIR --trips DIR --out REPO

Inputs (no scrapers here):
  --gtfs   the official Telangana open-data GTFS (Hyderabad city routes), extracted
  --trips  trip files collected by reclaim.city from the TGSRTC Bus Tracking service
           (raw/trips/YYYYMMDD/<vehicleId>_<reg>.json.gz): a service's stops with planned
           times, the times the bus actually reached them, and its GPS line

Output (REPO/data):
  tgsrtc-gtfs.zip            the combined GTFS: every official file as published, plus routes,
                             trips, stop_times, stops and shapes for the collected services that
                             the official feed does not carry (ids prefixed `tgc-`)
  gtfs/                      the small files unzipped (agency, feed_info, calendar, routes, trips, stops)
  trip_observations.csv.gz   per collected service-day and stop: planned, arrived and left (IST)
  stats.json

A collected service is "already in the GTFS" when its route number is an official route
number; those are kept out of the GTFS (the official timetable stands) but their observed
times are kept in trip_observations. Stops within 100 m of an official stop with the same
name reuse its stop_id. No driver data exists in any input or output.
"""
import argparse, collections, csv, datetime as dt, glob, gzip, hashlib, io, json, math, os, re, shutil, zipfile

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
place = lambda n: re.sub(r'\s+twd\b.*$', '', str(n or ''), flags=re.I).strip()
key = lambda n: re.sub(r'[^A-Z0-9]', '', place(n).upper())
slug = lambda x: re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', str(x or '').lower()))


def centroid(g):
    """A stop's point: its Point, or the middle of a bus station's geofence polygon."""
    if not g:
        return None, None
    c = g.get('coordinates')
    if g.get('type') == 'Point':
        return c[1], c[0]
    ring = c[0] if g.get('type') == 'Polygon' else c[0][0]
    return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)


def norm(d):
    """One archive snapshot (raw/trips/<day>/<serviceId>_<veh>.json.gz) in the builder's shape."""
    if 'points' not in d:
        return d                                       # already a map trip file
    stops = []
    for q in sorted(d['points'], key=lambda q: q.get('sequence') or 0):
        la, lo = centroid(q.get('geometry'))
        stops.append([q.get('name'), la, lo, q.get('plannedTime') or 0, q.get('entryTime') or 0, q.get('exitTime') or 0, q.get('id')])
    return dict(sid=d.get('serviceId'), trip=d.get('id'), route=d.get('serviceName'), type=d.get('serviceType'), depot=d.get('depotName'),
                veh=d.get('vehicleNumber'), cols=['stop', 'lat', 'lon', 'plan', 'entry', 'exit', 'sid'], stops=stops,
                line=[[p['lat'], p['lng']] for p in d.get('polylinePoints') or []])


def main():
    ap = argparse.ArgumentParser()
    for k in ('gtfs', 'trips', 'out'):
        ap.add_argument('--' + k, required=True)
    a = ap.parse_args()
    out = os.path.join(a.out, 'data'); gd = os.path.join(out, 'gtfs')
    shutil.rmtree(gd, ignore_errors=True); os.makedirs(gd)

    # official stops, on a ~100 m grid, to reuse their ids
    ostops, grid = {}, collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(a.gtfs, 'stops.txt'), encoding='utf-8-sig')):
        la, lo = float(r['stop_lat']), float(r['stop_lon'])
        ostops[r['stop_id']] = (r['stop_name'], la, lo)
        grid[(round(la * 1000), round(lo * 1000))].append(r['stop_id'])
    oroutes = {r['route_short_name'].strip().upper().replace(' ', '') for r in csv.DictReader(open(os.path.join(a.gtfs, 'routes.txt'), encoding='utf-8-sig'))}

    def official_stop(name, la, lo):
        k = key(name)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for sid in grid.get((round(la * 1000) + dx, round(lo * 1000) + dy), []):
                    n, sla, slo = ostops[sid]
                    if key(n) == k and math.hypot((sla - la) * 111000, (slo - lo) * 106000) < 100:
                        return sid
        return None

    # collected trips: newest file of each service wins (it has the fullest record)
    files = sorted(glob.glob(os.path.join(a.trips, '*', '*.json.gz')))
    best, obs_rows = {}, []
    for p in files:
        try:
            d = norm(json.load(gzip.open(p)))
        except Exception:
            continue
        sid = str(d.get('sid') or '')
        if not sid or not d.get('stops'):
            continue
        C = {c: i for i, c in enumerate(d['cols'])}
        day = os.path.basename(os.path.dirname(p))
        for i, s in enumerate(d['stops']):
            f = lambda t: dt.datetime.fromtimestamp(t, IST).strftime('%Y-%m-%d %H:%M:%S') if t else ''
            obs_rows.append([sid, day, d.get('trip', ''), d.get('route', ''), d.get('type', ''), d.get('depot', ''), d.get('veh', ''), i + 1,
                             s[C['stop']], s[C['lat']], s[C['lon']], f(s[C['plan']]), f(s[C['entry']]), f(s[C['exit']])])
        prev = best.get(sid)
        if not prev or (len(d['stops']), bool(d.get('line'))) >= (len(prev[0]['stops']), bool(prev[0].get('line'))):
            best[sid] = (d, C)

    new_stops, routes, trips, st_rows, shapes = {}, {}, [], [], []
    skipped_official = 0
    for sid, (d, C) in best.items():
        rn = str(d.get('route') or '').strip()
        if rn.upper().replace(' ', '') in oroutes:
            skipped_official += 1
            continue
        plans = [s[C['plan']] for s in d['stops']]
        if not plans or not plans[0] or not plans[-1]:
            continue
        t0 = dt.datetime.fromtimestamp(plans[0], IST)
        midnight = t0.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        ids = []
        for s in d['stops']:
            n, la, lo = s[C['stop']], s[C['lat']], s[C['lon']]
            if not la or not lo:
                ids.append(None); continue
            o = official_stop(n, la, lo)
            if not o:
                own = s[C['sid']] if 'sid' in C else None
                o = f'tgc-{own}' if own else 'tgc-' + hashlib.md5(f'{key(n)}|{la:.4f}|{lo:.4f}'.encode()).hexdigest()[:10]
                new_stops.setdefault(o, (place(n).title() if n == n.upper() else place(n), la, lo))
            ids.append(o)
        if sum(1 for x in ids if x) < 2:
            continue
        typ = str(d.get('type') or '').title()
        rid = 'tgc-' + slug(f'{rn}-{typ}') if rn else 'tgc-' + slug(f'{d["stops"][0][C["stop"]]}-{d["stops"][-1][C["stop"]]}')
        first, last = place(d['stops'][0][C['stop']]), place(d['stops'][-1][C['stop']])
        r = routes.setdefault(rid, [rn or f'{first}–{last}', f'{first} – {last}', typ, d.get('depot', ''), 0])
        r[4] += 1
        tid = 'tgc-' + sid
        trips.append([rid, 'daily', tid, str(d.get('trip', '')), last, tid if d.get('line') else '', typ])
        seq = 0
        for s, sidd in zip(d['stops'], ids):
            if not sidd:
                continue
            seq += 1
            t = s[C['plan']]
            if t:
                x = int(round((t - midnight) / 60)); tt = f'{x // 60:02d}:{x % 60:02d}:00'
            else:
                tt = ''
            st_rows.append([tid, tt, tt, sidd, seq, 1 if t else 0])
        # the GPS line, thinned to a point every ~80 m and at most 600 points (raw lines carry thousands)
        kept, last = [], None
        for la, lo in d.get('line') or []:
            if last is None or math.hypot((la - last[0]) * 111000, (lo - last[1]) * 106000) >= 80:
                kept.append((la, lo)); last = (la, lo)
        if d.get('line') and kept[-1] != tuple(d['line'][-1]):
            kept.append(tuple(d['line'][-1]))
        if len(kept) > 600:
            st_ = len(kept) / 599; kept = [kept[min(len(kept) - 1, round(i * st_))] for i in range(600)]
        for i, (la, lo) in enumerate(kept):
            shapes.append([tid, f'{la:.5f}', f'{lo:.5f}', i + 1])

    # official files as published, plus ours appended
    zp = os.path.join(out, 'tgsrtc-gtfs.zip')
    add = {
        'routes.txt': (['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type'],
                       [[rid, '', r[0], r[1], f'{r[2]} · {r[3]} depot · collected by reclaim.city', 3] for rid, r in routes.items()]),
        'trips.txt': (['route_id', 'service_id', 'trip_id', 'trip_short_name', 'trip_headsign', 'shape_id', 'trip_type'], trips),
        'stop_times.txt': (['trip_id', 'arrival_time', 'departure_time', 'stop_id', 'stop_sequence', 'timepoint'], st_rows),
        'stops.txt': (['stop_id', 'stop_name', 'stop_lat', 'stop_lon'], [[k, v[0], f'{v[1]:.6f}', f'{v[2]:.6f}'] for k, v in new_stops.items()]),
        'shapes.txt': (['shape_id', 'shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence'], shapes),
    }
    agency_id = next(csv.DictReader(open(os.path.join(a.gtfs, 'agency.txt'), encoding='utf-8-sig'))).get('agency_id', '')
    for row in add['routes.txt'][1]:
        row[1] = agency_id
    have_cal = os.path.exists(os.path.join(a.gtfs, 'calendar.txt'))
    counts = {}
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(os.listdir(a.gtfs)):
            if not name.endswith('.txt'):
                continue
            src = open(os.path.join(a.gtfs, name), encoding='utf-8-sig').read().splitlines()
            hdr = next(csv.reader([src[0]]))
            # optional GTFS columns our rows carry (route_desc, trip_headsign) join the header; official rows leave them empty
            extra = [c for c in (add[name][0] if name in add else []) if c not in hdr and c in ('route_desc', 'trip_headsign')]
            buf = io.StringIO(); w = csv.writer(buf, lineterminator='\n')
            buf.write(','.join(hdr + extra) + '\n')
            for ln in src[1:]:
                buf.write(ln + ',' * len(extra) + '\n')
            hdr = hdr + extra
            if name in add:
                h2, rows = add[name]
                for row in rows:
                    m = dict(zip(h2, row)); w.writerow([m.get(c, '') for c in hdr])
            if name == 'calendar.txt':
                w.writerow([{'service_id': 'daily', 'start_date': '20261101', 'end_date': '20271031'}.get(c, '1') for c in hdr])
            data = buf.getvalue()
            counts[name] = data.count('\n') - 1
            z.writestr(name, data)
            if name not in ('stop_times.txt', 'shapes.txt'):
                open(os.path.join(gd, name), 'w').write(data)

    with gzip.open(os.path.join(out, 'trip_observations.csv.gz'), 'wt', newline='') as fo:
        w = csv.writer(fo)
        w.writerow(['service_id', 'day', 'trip', 'route', 'service_type', 'depot', 'vehicle', 'stop_sequence', 'stop', 'lat', 'lon', 'planned', 'arrived', 'left'])
        w.writerows(obs_rows)
    stats = dict(official=dict(routes=len(oroutes), stops=len(ostops)), collected_services=len(best), collected_in_official=skipped_official,
                 added_routes=len(routes), added_trips=len(trips), added_stops=len(new_stops), added_stop_times=len(st_rows),
                 combined=counts, observation_rows=len(obs_rows), days=sorted({os.path.basename(os.path.dirname(p)) for p in files}),
                 service_types=dict(collections.Counter(r[2] for r in routes.values())))
    json.dump(stats, open(os.path.join(out, 'stats.json'), 'w'), indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == '__main__':
    main()
