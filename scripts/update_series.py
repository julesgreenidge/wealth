"""Price history for the charts on the Performance tab. Public data only. Writes series.json:
  d: daily closes for about the last 13 months
  w: weekly closes (Fridays) for up to 10 years
  h: hourly prices for the latest trading day (shares and crypto; funds are priced once a day)
Prices are in pounds (UK shares in pence, as on FT); US shares are converted at the ECB rate for each day."""
import json, re, sys, time, datetime as dt, urllib.request
from update_history import FT, KRAKEN, USD, UA, get, ft_xid

def ft_daily(xid, start, end):
    """Daily closes between two dates, fetched a year at a time."""
    out = {}
    a = start
    while a <= end:
        b = min(end, a + dt.timedelta(days=360))
        j = json.loads(get(f'https://markets.ft.com/data/equities/ajax/get-historical-prices?startDate={a:%Y/%m/%d}&endDate={b:%Y/%m/%d}&symbol={xid}'))
        for row in re.findall(r'<tr>(.*?)</tr>', j.get('html', ''), re.S):
            d = re.search(r'([A-Z][a-z]+, [A-Z][a-z]+ \d{1,2}, \d{4})', row)
            cells = re.findall(r'<td[^>]*>([\d,\.]+)</td>', row)
            if d and len(cells) >= 4:
                out[dt.datetime.strptime(d.group(1), '%A, %B %d, %Y').date()] = float(cells[3].replace(',', ''))
        a = b + dt.timedelta(days=1); time.sleep(0.3)
    return sorted(out.items())

def ft_hourly(xid):
    """Hourly prices for the latest trading day, from FT's chart service."""
    body = json.dumps({'days': 1, 'dataNormalized': False, 'dataPeriod': 'Hour', 'dataInterval': 1, 'realtime': False,
                       'yFormat': '0.###', 'timeServiceFormat': 'JSON', 'returnDateType': 'ISO8601',
                       'elements': [{'Label': 'p', 'Type': 'price', 'Symbol': xid, 'OverlayIndicators': [], 'Params': {}}]}).encode()
    req = urllib.request.Request('https://markets.ft.com/data/chartapi/series', data=body,
                                 headers={**UA, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r: j = json.load(r)
    dates = j.get('Dates') or []
    comp = next(c for c in j['Elements'][0]['ComponentSeries'] if c['Type'] == 'Close')
    return [(d[:16], v) for d, v in zip(dates, comp['Values']) if v is not None]

def kraken(pair, minutes):
    j = json.loads(get(f'https://api.kraken.com/0/public/OHLC?interval={minutes}&pair={pair}'))
    if j.get('error'): raise ValueError(j['error'])
    return [(dt.datetime.utcfromtimestamp(int(r[0])), float(r[4])) for r in list(j['result'].values())[0]]

def fx_series(start, end):
    j = json.loads(get(f'https://api.frankfurter.app/{start:%Y-%m-%d}..{end:%Y-%m-%d}?from=GBP&to=USD'))
    return sorted((dt.date.fromisoformat(d), v['USD']) for d, v in j['rates'].items())

def to_gbp(rows, fx):
    out, i, rate = [], 0, fx[0][1]
    for d, p in rows:
        while i < len(fx) and fx[i][0] <= d: rate = fx[i][1]; i += 1
        out.append((d, p / rate))
    return out

def weekly(rows):
    wk = {}
    for d, p in rows: wk[d - dt.timedelta(days=d.weekday())] = (d, p)   # last close in each week
    return [v for _, v in sorted(wk.items())]

def r(p): return round(p, 4 if p < 10 else 2)

def main(out='series.json'):
    today = dt.date.today(); start = today.replace(year=today.year - 10) - dt.timedelta(days=7)
    try: old = json.load(open(out))['assets']
    except Exception: old = {}
    fx = fx_series(start, today)
    assets = {}
    for key, (sym, kind) in FT.items():
        rec = {}
        try:
            xid = ft_xid(sym, kind)
            rows = ft_daily(xid, start, today)
            if key in USD: rows = to_gbp(rows, fx)
            cut = today - dt.timedelta(days=400)
            rec['d'] = [[str(d), r(p)] for d, p in rows if d >= cut]
            rec['w'] = [[str(d), r(p)] for d, p in weekly(rows)]
            if kind == 'equities':
                try:
                    h = ft_hourly(xid)
                    rate = fx[-1][1] if key in USD else 1
                    rec['h'] = [[t, r(p / rate)] for t, p in h]
                except Exception as e: print(f'  {key}: no hourly prices ({type(e).__name__})')
        except Exception as e:
            print(f'  {key}: FAILED ({type(e).__name__}: {e}), keeping previous'); rec = old.get(key, {})
        assets[key] = rec
        print(f"  {key}: {len(rec.get('d', []))} daily, {len(rec.get('w', []))} weekly, {len(rec.get('h', []))} hourly")
        time.sleep(0.3)
    for key, pair in KRAKEN.items():
        rec = {}
        try:
            d = [(t.date(), p) for t, p in kraken(pair, 1440)]
            w = [(t.date() + dt.timedelta(days=6), p) for t, p in kraken(pair, 10080)]
            h = kraken(pair, 60)
            rec['d'] = [[str(a), r(p)] for a, p in d if a >= today - dt.timedelta(days=400)]
            rec['w'] = [[str(a), r(p)] for a, p in w if a >= start]
            last = h[-1][0]
            rec['h'] = [[t.strftime('%Y-%m-%dT%H:%M'), r(p)] for t, p in h if t > last - dt.timedelta(hours=24)]
        except Exception as e:
            print(f'  {key}: FAILED ({type(e).__name__}: {e}), keeping previous'); rec = old.get(key, {})
        assets[key] = rec
        print(f"  {key}: {len(rec.get('d', []))} daily, {len(rec.get('w', []))} weekly, {len(rec.get('h', []))} hourly")
    json.dump(dict(updated=str(today), assets=assets), open(out, 'w'), separators=(',', ':'))

if __name__ == '__main__':
    main(*sys.argv[1:])
