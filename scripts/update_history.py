"""Price performance of each investment over 1, 3, 5 and 10 years (price change only, in the asset's own currency).
Public data only. Writes history.json."""
import json, re, datetime as dt, urllib.request, sys, time

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'}
FT = {  # key: (FT symbol, kind)
 'GAC': ('GB00BD3RZ582:GBP', 'funds'), 'AVUSEQ': ('GB00B0ZY5X49:GBP', 'funds'), 'USEQ': ('GB00B5B71Q71:GBP', 'funds'), 'LS100': ('GB00B41XG308:GBP', 'funds'),
 'MSFT': ('MSFT:NSQ', 'equities'), 'AAPL': ('AAPL:NSQ', 'equities'), 'AMD': ('AMD:NSQ', 'equities'), 'META': ('META:NSQ', 'equities'),
 'NVDA': ('NVDA:NSQ', 'equities'), 'AMZN': ('AMZN:NSQ', 'equities'), 'GOOGL': ('GOOGL:NSQ', 'equities'), 'DIS': ('DIS:NYQ', 'equities'),
 'PEP': ('PEP:NSQ', 'equities'), 'AAF': ('AAF:LSE', 'equities')}
KRAKEN = {'BTC': 'XBTGBP', 'ETH': 'ETHGBP'}
YEARS = [1, 3, 5, 10]

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode('utf-8', 'replace')

def ft_xid(sym, kind):
    h = get(f'https://markets.ft.com/data/{kind}/tearsheet/summary?s={sym}')
    m = re.search(r'xid(?:&quot;|")\s*:\s*(?:&quot;|")(\d+)', h)
    if not m: raise ValueError('xid not found')
    return m.group(1)

def ft_close_near(xid, day):
    """Closing price on the last trading day on or before `day` (looks back up to 10 days)."""
    a, b = day - dt.timedelta(days=10), day
    j = json.loads(get(f'https://markets.ft.com/data/equities/ajax/get-historical-prices?startDate={a:%Y/%m/%d}&endDate={b:%Y/%m/%d}&symbol={xid}'))
    rows = re.findall(r'<tr>(.*?)</tr>', j.get('html', ''), re.S)
    best = None
    for row in rows:
        d = re.search(r'([A-Z][a-z]+, [A-Z][a-z]+ \d{1,2}, \d{4})', row)
        cells = re.findall(r'<td[^>]*>([\d,\.]+)</td>', row)
        if not d or len(cells) < 4: continue
        date = dt.datetime.strptime(d.group(1), '%A, %B %d, %Y').date()
        close = float(cells[3].replace(',', ''))
        if date <= day and (best is None or date > best[0]): best = (date, close)
    if not best: raise ValueError('no price in window')
    return best

def kraken_weekly(pair):
    j = json.loads(get(f'https://api.kraken.com/0/public/OHLC?interval=10080&pair={pair}'))
    if j.get('error'): raise ValueError(j['error'])
    rows = list(j['result'].values())[0]
    return [(dt.datetime.utcfromtimestamp(int(r[0])).date() + dt.timedelta(days=6), float(r[4])) for r in rows]  # week end, close

def main(prices_path='prices.json', out='history.json'):
    today = dt.date.today()
    prices = json.load(open(prices_path))['items']
    try: old = json.load(open(out))['assets']
    except Exception: old = {}
    assets = {}
    for key, (sym, kind) in FT.items():
        now = prices.get(key, {}).get('price')
        rec = dict(now=now, now_date=prices.get(key, {}).get('date'), src='FT', periods={})
        try:
            xid = ft_xid(sym, kind)
            for y in YEARS:
                target = today.replace(year=today.year - y)
                try:
                    d, p = ft_close_near(xid, target)
                    rec['periods'][str(y)] = dict(start=p, start_date=str(d), change=round(now / p - 1, 6) if now else None)
                except Exception as e:
                    rec['periods'][str(y)] = None
                    print(f'  {key} {y}y: no data ({e})')
                time.sleep(0.4)
        except Exception as e:
            print(f'  {key}: FAILED ({e}), keeping previous'); rec = old.get(key, rec)
        assets[key] = rec
        print(f'  {key}: ' + ', '.join(f"{y}y={rec['periods'].get(str(y), {}) and rec['periods'][str(y)]['change']}" for y in YEARS))
    for key, pair in KRAKEN.items():
        now = prices.get(key, {}).get('price')
        rec = dict(now=now, now_date=prices.get(key, {}).get('date'), src='Kraken (weekly closes)', periods={})
        try:
            weeks = kraken_weekly(pair)
            for y in YEARS:
                target = today.replace(year=today.year - y)
                cand = [w for w in weeks if w[0] <= target]
                if cand and (target - cand[-1][0]).days <= 10:
                    d, p = cand[-1]; rec['periods'][str(y)] = dict(start=p, start_date=str(d), change=round(now / p - 1, 6) if now else None)
                else: rec['periods'][str(y)] = None
        except Exception as e:
            print(f'  {key}: FAILED ({e}), keeping previous'); rec = old.get(key, rec)
        assets[key] = rec
        print(f'  {key}: ' + ', '.join(f"{y}y={rec['periods'].get(str(y), {}) and rec['periods'][str(y)]['change']}" for y in YEARS))
    json.dump(dict(updated=str(today), assets=assets), open(out, 'w'), indent=1)

if __name__ == '__main__':
    main(*sys.argv[1:])
