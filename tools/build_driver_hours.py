#!/usr/bin/env python3
"""TGSRTC driver working hours, pseudonymised for publication.

    build_driver_hours.py --src driver_hours.csv --key KEYFILE --out REPO

The source rows (one per driver per day, from the TGSRTC driver store) carry a driver hash.
Before publishing, that hash is replaced by a new pseudonym, HMAC-SHA256 under a secret key
that is never published (KEYFILE, kept out of the repository): stable from day to day, so one
driver's hours can be followed over time, but impossible to map back to a person, even for
someone who holds a list of staff or licence numbers. No names, staff or licence numbers or
phone numbers exist in the source or the output.

Output (REPO/data/drivers):
  driver_hours.csv.gz   per pseudonymous driver and day (id_basis: "name+mobile" = one person;
                        "name" = drivers sharing a name at a depot may be merged): depot, routes, service type, trips,
                        buses, planned and observed first/last hour (rounded to the hour),
                        span and driving hours (to the quarter hour); rows where one id was on two
                        buses at once (drivers sharing a name) are left out
  depot_hours.csv       per depot and day: drivers, trips, median and 90th-percentile planned
                        and observed driving hours, drivers over 8 h and over 10 h planned,
                        shared-name rows left out
"""
import argparse, collections, csv, gzip, hashlib, hmac, os, secrets, statistics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True); ap.add_argument('--key', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    if not os.path.exists(a.key):
        with open(a.key, 'w') as f:
            f.write(secrets.token_hex(32))
        os.chmod(a.key, 0o600)
    key = bytes.fromhex(open(a.key).read().strip())
    # written in groups of four (d-04e8-95e2-ca58-8a33), so no run of digits can look like a phone number
    pseud = lambda h: (lambda x: 'd-' + '-'.join(x[i:i + 4] for i in range(0, 16, 4)))(hmac.new(key, h.encode(), hashlib.sha256).hexdigest()[:16])
    allrows = list(csv.DictReader(open(a.src)))
    # overlap: one id on two buses at once in a depot = two drivers who share a name; not a person's day, so left out
    # left out: one id on two buses at once (drivers sharing a name), and placeholder "names" (a depot,
    # route or bus type typed in the name field) — neither is one person's day
    drop = lambda r: r.get('overlap') == 'True' or r.get('id_basis') == 'placeholder'
    rows = [r for r in allrows if not drop(r)]
    over = collections.Counter((r['date'], r['depot']) for r in allrows if drop(r))
    num0 = lambda v: float(v) if v not in ('', None) else 0.0
    # kept but marked: a day no one person works (span over 16 h, or more than 3 buses)
    ok = lambda r: num0(r.get('planned_span_h')) <= 16 and num0(r.get('actual_span_h')) <= 16 and int(r.get('buses') or 0) <= 3
    # a margin against matching a row to a person: times to the hour, hours to the quarter
    hr = lambda t: f'{t[:2]}:00' if t and len(t) >= 2 else ''
    qh = lambda v: f'{round(float(v) * 4) / 4:g}' if v not in ('', None) else ''
    out = os.path.join(a.out, 'data', 'drivers'); os.makedirs(out, exist_ok=True)
    cols = ['driver', 'id_basis', 'date', 'depot', 'routes', 'service_type', 'trips', 'buses', 'planned_first', 'planned_last', 'planned_span_h',
            'planned_driving_h', 'actual_first', 'actual_last', 'actual_span_h', 'actual_driving_h', 'reliable']
    with gzip.open(os.path.join(out, 'driver_hours.csv.gz'), 'wt', newline='') as f:
        w = csv.writer(f); w.writerow(cols)
        for r in sorted(rows, key=lambda r: (r['date'], r['depot'], pseud(r['driver_hash']))):
            v = dict(r)
            for c in ('planned_first', 'planned_last', 'actual_first', 'actual_last'): v[c] = hr(r.get(c))
            for c in ('planned_span_h', 'planned_driving_h', 'actual_span_h', 'actual_driving_h'): v[c] = qh(r.get(c))
            v['reliable'] = 1 if ok(r) else 0
            w.writerow([pseud(r['driver_hash'])] + [v.get(c, '') for c in cols[1:]])
    g = collections.defaultdict(list)
    unrel = collections.Counter((r['date'], r['depot']) for r in rows if not ok(r))
    for r in rows:
        if ok(r):
            g[(r['date'], r['depot'])].append(r)
    num = lambda v: float(v) if v not in ('', None) else None
    q = lambda v, p: sorted(v)[int(p * (len(v) - 1))] if v else ''
    with open(os.path.join(out, 'depot_hours.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'depot', 'drivers', 'trips', 'median_planned_driving_h', 'p90_planned_driving_h',
                    'median_actual_driving_h', 'p90_actual_driving_h', 'drivers_over_8h_planned', 'drivers_over_10h_planned', 'rows_left_out', 'rows_unreliable'])
        for (d, dep), rs in sorted(g.items()):
            pl = [x for x in (num(r['planned_driving_h']) for r in rs) if x is not None]
            ac = [x for x in (num(r['actual_driving_h']) for r in rs) if x is not None]
            w.writerow([d, dep, len(rs), sum(int(r['trips'] or 0) for r in rs),
                        round(statistics.median(pl), 2) if pl else '', round(q(pl, .9), 2) if pl else '',
                        round(statistics.median(ac), 2) if ac else '', round(q(ac, .9), 2) if ac else '',
                        sum(1 for x in pl if x > 8), sum(1 for x in pl if x > 10), over.get((d, dep), 0), unrel.get((d, dep), 0)])
    print(f'{len(allrows) - len(rows)} rows left out (shared name / placeholder), {sum(unrel.values())} marked unreliable;', end=' ')
    print(f'{len(rows)} driver-days, {len({r["driver_hash"] for r in rows})} drivers, {len(g)} depot-days -> {out}')


if __name__ == '__main__':
    main()
