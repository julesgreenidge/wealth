"""Fetch the latest prices and write prices.json (no personal data: prices only).
Each price has fallbacks; if every source fails, the previous price is kept."""
import json, re, datetime as dt, urllib.request, urllib.parse, csv, io, sys

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
      'Accept-Language': 'en-GB,en;q=0.9'}
FUNDS = {'GAC': 'GB00BD3RZ582', 'USEQ': 'GB00B5B71Q71', 'LS100': 'GB00B41XG308'}
US = ['MSFT', 'AAPL', 'AMD', 'META', 'NVDA', 'AMZN', 'GOOGL', 'DIS', 'PEP']
CRYPTO = {'BTC': 'bitcoin', 'ETH': 'ethereum'}

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')

def today(ts=None):
    return (dt.datetime.utcfromtimestamp(ts) if ts else dt.datetime.utcnow()).date().isoformat()

def yahoo(sym):
    j = json.loads(get('https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(sym) + '?range=5d&interval=1d'))
    m = j['chart']['result'][0]['meta']
    return float(m['regularMarketPrice']), today(m.get('regularMarketTime')), m.get('currency')

def stooq(sym):
    rows = list(csv.DictReader(io.StringIO(get('https://stooq.com/q/l/?s=' + sym + '&f=sd2c&h&e=csv'))))
    r = rows[0]
    if r.get('Close') in (None, '', 'N/D'): raise ValueError('no data')
    return float(r['Close']), r['Date']

def ft_fund(isin):
    h = get('https://markets.ft.com/data/funds/tearsheet/summary?s=' + isin + ':GBP')
    m = re.search(r'Price \(GBP\)</span><span class="mod-ui-data-list__value">([\d,\.]+)<', h)
    if not m: raise ValueError('price not found')
    d = re.search(r'as of ([A-Z][a-z]{2} \d{1,2} \d{4})', h)
    date = dt.datetime.strptime(d.group(1), '%b %d %Y').date().isoformat() if d else today()
    return float(m.group(1).replace(',', '')), date

def yahoo_isin(isin):
    j = json.loads(get('https://query2.finance.yahoo.com/v1/finance/search?q=' + isin))
    sym = j['quotes'][0]['symbol']
    p, d, cur = yahoo(sym)
    if cur == 'GBp': p = p / 100
    return p, d

def first(name, *fns):
    errs = []
    for label, fn in fns:
        try:
            out = fn()
            print(f'  {name}: {out[0]} ({out[1]}) from {label}')
            return out + (label,)
        except Exception as e:
            errs.append(f'{label}: {e}')
    print(f'  {name}: FAILED ({"; ".join(errs)})')
    return None

def main(path='prices.json'):
    try: old = json.load(open(path))
    except Exception: old = {'items': {}, 'fx': {}}
    items, failed = dict(old.get('items', {})), []
    for k, isin in FUNDS.items():
        r = first(k, ('FT', lambda isin=isin: ft_fund(isin)), ('Yahoo', lambda isin=isin: yahoo_isin(isin)))
        if r: items[k] = dict(price=r[0], date=r[1], cur='GBP', src=r[2])
        else: failed.append(k)
    for t in US:
        r = first(t, ('Yahoo', lambda t=t: yahoo(t)[:2]), ('Stooq', lambda t=t: stooq(t.lower() + '.us')))
        if r: items[t] = dict(price=r[0], date=r[1], cur='USD', src=r[2])
        else: failed.append(t)
    def aaf_yahoo():
        p, d, cur = yahoo('AAF.L')
        return (p if cur == 'GBp' else p * 100), d
    r = first('AAF', ('Yahoo', aaf_yahoo), ('Stooq', lambda: stooq('aaf.uk')))
    if r: items['AAF'] = dict(price=r[0], date=r[1], cur='GBp', src=r[2])
    else: failed.append('AAF')
    try:
        j = json.loads(get('https://api.coingecko.com/api/v3/simple/price?ids=' + ','.join(CRYPTO.values()) + '&vs_currencies=gbp&include_last_updated_at=true'))
        for k, cid in CRYPTO.items():
            items[k] = dict(price=float(j[cid]['gbp']), date=today(j[cid].get('last_updated_at')), cur='GBP', src='CoinGecko')
            print(f'  {k}: {items[k]["price"]} from CoinGecko')
    except Exception as e:
        print('  crypto FAILED', e); failed += list(CRYPTO)
    fx = old.get('fx', {})
    r = first('GBPUSD', ('ECB (Frankfurter)', lambda: (lambda j: (float(j['rates']['USD']), j['date']))(json.loads(get('https://api.frankfurter.app/latest?from=GBP&to=USD')))),
              ('Yahoo', lambda: yahoo('GBPUSD=X')[:2]))
    if r: fx = {'usd': dict(rate=r[0], date=r[1], src=r[2])}
    else: failed.append('GBPUSD')
    out = dict(updated=dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), fx=fx, items=items, failed=failed)
    json.dump(out, open(path, 'w'), indent=1)
    print('failed:', failed or 'none')

if __name__ == '__main__':
    main(*sys.argv[1:])
