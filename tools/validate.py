import csv, io, sys, zipfile, collections
z = zipfile.ZipFile(sys.argv[1]); rd = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), encoding='utf-8-sig'))
need = ['agency.txt', 'stops.txt', 'routes.txt', 'trips.txt', 'stop_times.txt']
names = set(z.namelist()); print('files:', sorted(names)); assert all(n in names for n in need), 'missing required file'
routes = {r['route_id'] for r in rd('routes.txt')}; stops = {r['stop_id'] for r in rd('stops.txt')}
cal = {r['service_id'] for r in rd('calendar.txt')} if 'calendar.txt' in names else set()
shapes = set(); 
for r in rd('shapes.txt'): shapes.add(r['shape_id'])
bad = collections.Counter(); trips = {}
for t in rd('trips.txt'):
    trips[t['trip_id']] = t
    if t['route_id'] not in routes: bad['trip route missing'] += 1
    if cal and t['service_id'] not in cal: bad['trip service_id missing'] += 1
    if t.get('shape_id') and t['shape_id'] not in shapes: bad['trip shape missing'] += 1
seen = collections.defaultdict(list)
for r in rd('stop_times.txt'):
    if r['stop_id'] not in stops: bad['stop_time stop missing'] += 1
    if r['trip_id'] not in trips: bad['stop_time trip missing'] += 1
    seen[r['trip_id']].append((int(r['stop_sequence']), r['arrival_time']))
for tid, v in seen.items():
    v.sort()
    if not v[0][1] or not v[-1][1]: bad['trip without first/last time'] += 1
no_st = sum(1 for t in trips if t not in seen)
if no_st: bad['trip without stop_times'] = no_st
dup = len(trips) - len(set(trips)); print(f'routes {len(routes):,} trips {len(trips):,} stops {len(stops):,} shapes {len(shapes):,} stop_time trips {len(seen):,}')
print('problems:', dict(bad) or 'none')
