#!/usr/bin/env python3
"""Statistics images for an RTC open-data repo, from its own GTFS and observations.

    charts.py --net apsrtc|tgsrtc --repo DIR

Writes DIR/screenshots/{network,departures,service-types,delays}.png (1200 x 630), drawn as
SVG in the bus maps' style (maps.reclaim.city) and rendered by headless Chromium."""
import argparse, asyncio, collections, csv, gzip, io, json, math, os, zipfile
from playwright.async_api import async_playwright

RED, INK, MUTED, PAPER, LINE = '#f01b48', '#1c1c1e', '#8a8a8e', '#f9f5ed', '#e7e2d6'


def hash_color(name):
    h = 0
    for ch in str(name):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return f'hsl({(h * 47) % 360} {62 + h % 18}% {42 + h % 12}%)'


def page(title, sub, body, foot):
    return f"""<!doctype html><meta charset=utf-8><style>
body{{margin:0;width:1200px;height:630px;background:{PAPER};font-family:-apple-system,'Segoe UI',Roboto,sans-serif;color:{INK};overflow:hidden}}
.h{{position:absolute;left:56px;top:44px}} .h b{{font-size:34px;font-weight:850;letter-spacing:-.02em;display:block}}
.h span{{font-size:18px;color:{MUTED}}} .f{{position:absolute;left:56px;bottom:30px;font-size:15px;color:{MUTED}}}
.f b{{color:{INK}}} svg text{{font-family:inherit}}</style>
<div class=h><b>{title}</b><span>{sub}</span></div>{body}<div class=f>{foot}</div>"""


def bars(items, x0, y0, w, h, color=RED, label_every=1, fmt=lambda v: f'{v:,}', horizontal=False):
    mx = max(v for _, v in items) or 1
    out = []
    if horizontal:
        bh = h / len(items)
        for i, (k, v) in enumerate(items):
            y = y0 + i * bh; bw = (w - 300) * v / mx
            out.append(f'<text x="{x0 + 290}" y="{y + bh * .62}" text-anchor="end" font-size="15" fill="{INK}">{k}</text>'
                       f'<rect x="{x0 + 300}" y="{y + bh * .18}" width="{bw:.1f}" height="{bh * .64:.1f}" rx="4" fill="{color if isinstance(color, str) else color(k)}"/>'
                       f'<text x="{x0 + 306 + bw:.1f}" y="{y + bh * .62}" font-size="14" font-weight="700" fill="{MUTED}">{fmt(v)}</text>')
        return ''.join(out)
    bw = w / len(items)
    for i, (k, v) in enumerate(items):
        bh_ = h * v / mx; x = x0 + i * bw
        out.append(f'<rect x="{x + bw * .12:.1f}" y="{y0 + h - bh_:.1f}" width="{bw * .76:.1f}" height="{bh_:.1f}" rx="3" fill="{color if isinstance(color, str) else color(k)}"><title>{k}: {fmt(v)}</title></rect>')
        if i % label_every == 0:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{y0 + h + 22}" text-anchor="middle" font-size="13" fill="{MUTED}">{k}</text>')
    return ''.join(out)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--net', required=True); ap.add_argument('--repo', required=True)
    a = ap.parse_args()
    NET = a.net.upper(); data = os.path.join(a.repo, 'data'); shots = os.path.join(a.repo, 'screenshots'); os.makedirs(shots, exist_ok=True)
    z = zipfile.ZipFile(os.path.join(data, f'{a.net}-gtfs.zip'))
    rd = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), encoding='utf-8-sig'))
    routes = {r['route_id']: r for r in rd('routes.txt')}
    trips = {r['trip_id']: r for r in rd('trips.txt')}
    # departures by hour and trips by kind
    first = {}
    for r in rd('stop_times.txt'):
        if r['stop_sequence'] in ('1', '0') and r['departure_time']:
            first[r['trip_id']] = int(r['departure_time'][:2]) % 24
    hours = collections.Counter(first.values())
    kind = collections.Counter()
    for t in trips.values():
        k = t.get('trip_type') or ''
        if not k:
            d = routes.get(t['route_id'], {}).get('route_desc', '')
            if a.net == 'tgsrtc':
                k = d.split('·')[0].strip() if t['route_id'].startswith('tgc-') and '·' in d else 'City (official GTFS)'
            else:
                k = d.split('·')[1].strip() if '·' in d else 'Other'
            k = k or 'Other'
        kind[k.title() if k.isupper() else k] += 1
    # network: one line per route (its longest shape), thinned
    shp = collections.defaultdict(list)
    want = {}
    for t in trips.values():
        if t.get('shape_id'):
            want.setdefault(t['route_id'], t['shape_id'])
    keep = set(want.values())
    for r in rd('shapes.txt'):
        if r['shape_id'] in keep:
            shp[r['shape_id']].append((float(r['shape_pt_lon']), float(r['shape_pt_lat'])))
    pts = [p for v in shp.values() for p in v]
    xs, ys = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
    q = lambda s, f: s[int(f * (len(s) - 1))]
    W0, E0, S0, N0 = q(xs, .005), q(xs, .995), q(ys, .005), q(ys, .995)
    mx = lambda la: math.degrees(math.log(math.tan(math.pi / 4 + math.radians(la) / 2)))
    sx, sy = 640 / (E0 - W0), 560 / (mx(N0) - mx(S0)); k = min(sx, sy)
    ox, oy = 520 + (640 - (E0 - W0) * k) / 2, 40 + (560 - (mx(N0) - mx(S0)) * k) / 2
    P = lambda lo, la: f'{ox + (lo - W0) * k:.1f},{oy + (mx(N0) - mx(la)) * k:.1f}'
    lines = ''.join(f'<polyline points="{" ".join(P(*p) for p in v[::max(1, len(v) // 120)])}" fill="none" stroke="{hash_color(routes.get(rid, {}).get("route_short_name", rid))}" stroke-width="1.3" stroke-opacity=".7"/>'
                    for rid, sid in want.items() for v in [shp.get(sid, [])] if len(v) > 1)
    st = json.load(open(os.path.join(data, 'stats.json')))
    nstops = sum(1 for _ in rd('stops.txt'))
    facts = [(f'{len(routes):,}', 'routes'), (f'{len(trips):,}', 'trips a day'), (f'{nstops:,}', 'stops'), (f'{len(first):,}', 'timed departures')]
    fact_html = ''.join(f'<div style="margin-bottom:22px"><div style="font-size:42px;font-weight:850;color:{RED};font-variant-numeric:tabular-nums">{n}</div><div style="font-size:17px;color:{MUTED};font-weight:600">{l}</div></div>' for n, l in facts)
    imgs = {
        'network': page(f'{NET} network', 'every route in the GTFS, one line each, coloured by route number',
                        f'<div style="position:absolute;left:56px;top:170px">{fact_html}</div><svg width=1200 height=630 style="position:absolute;left:0;top:0">{lines}</svg>',
                        f'<b>github.com/reclaimchennai/{a.net}</b> · {a.net}-gtfs.zip · maps.reclaim.city/{a.net}'),
        'departures': page('Departures by hour', f'when {NET} trips start, from the timetables in the GTFS ({len(first):,} trips)',
                           f'<svg width=1200 height=630 style="position:absolute;left:0;top:0">{bars([(f"{h:02d}", hours.get(h, 0)) for h in range(24)], 56, 150, 1088, 380, label_every=2)}</svg>',
                           f'<b>{NET}</b> · busiest hour {max(hours, key=hours.get):02d}:00 · {hours[max(hours, key=hours.get)]:,} departures'),
        'service-types': page('Trips by kind of bus', f'{NET} trips a day by service type',
                              f'<svg width=1200 height=630 style="position:absolute;left:0;top:0">{bars(kind.most_common(12), 56, 140, 1088, 420, horizontal=True, color=lambda k: hash_color(k))}</svg>',
                              f'<b>{NET}</b> · {len(kind)} service types'),
    }
    # delays: APSRTC usual lateness per stop; TGSRTC observed arrival minus plan
    dl = collections.Counter()
    if a.net == 'apsrtc':
        for r in csv.DictReader(io.TextIOWrapper(gzip.open(os.path.join(data, 'stop_delays.csv.gz')), encoding='utf-8')):
            v = int(float(r['median_delay_min'])); dl[max(-15, min(60, 5 * round(v / 5)))] += 1
        what = 'usual lateness at each stop, median over a week of GPS'
    else:
        import datetime as dt
        p = lambda s: dt.datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
        for r in csv.DictReader(io.TextIOWrapper(gzip.open(os.path.join(data, 'trip_observations.csv.gz')), encoding='utf-8')):
            if r['planned'] and r['arrived']:
                v = (p(r['arrived']) - p(r['planned'])).total_seconds() / 60
                dl[max(-15, min(60, 5 * round(v / 5)))] += 1
        what = 'observed arrival minus the plan, every stop a tracked bus reached'
    if dl:
        items = [(('≤-15' if b == -15 else '60+' if b == 60 else f'{b:+d}'), dl.get(b, 0)) for b in range(-15, 61, 5)]
        tot = sum(dl.values()); late = sum(v for b, v in dl.items() if b >= 5)
        imgs['delays'] = page('How late the buses run', f'{NET}: {what} (minutes)',
                              f'<svg width=1200 height=630 style="position:absolute;left:0;top:0">{bars(items, 56, 150, 1088, 380, color=lambda k: "#2fa35a" if k in ("-5", "+0", "≤-15", "-10") else "#e0a100" if k in ("+5", "+10") else RED)}</svg>',
                              f'<b>{tot:,}</b> stop visits · <b>{100 * late / tot:.0f}%</b> five minutes late or more')

    async def render():
        async with async_playwright() as pw:
            b = await pw.chromium.launch()
            pg = await b.new_page(viewport={'width': 1200, 'height': 630})
            for n, html in imgs.items():
                await pg.set_content(html); await pg.wait_for_timeout(200)
                await pg.screenshot(path=os.path.join(shots, f'{n}.png'))
            await b.close()
    asyncio.run(render())
    print('charts:', ', '.join(imgs))


if __name__ == '__main__':
    main()
