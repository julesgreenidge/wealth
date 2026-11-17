"""Monthly update of fund make-up in funds.json (public data only, no personal figures).
Sources: Vanguard factsheet PDFs (countries, charges, yield, number of holdings, LifeStrategy regions),
Fidelity portfolio pages read by scripts/fund_pages.js (industries, company size, top 10 companies, regions),
FT holdings pages (LifeStrategy's underlying funds and their top companies, for a look-through).
Each figure is only replaced if it reads cleanly and looks sensible; otherwise the last good figure is kept
and the job fails at the end so GitHub emails the owner. Aviva's charge is never changed here."""
import html, json, re, subprocess, sys, urllib.request, datetime, copy
FUNDS_PATH, FID_PATH = sys.argv[1], sys.argv[2]
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'}
F = {  # page name -> ISIN, Vanguard factsheet PDF
 'Vanguard FTSE Global All Cap': ('GB00BD3RZ582', 'FTSE_Global_All_Cap_Index_Fund_8617_GBP_EN_UK.pdf'),
 'Vanguard US Equity Index': ('GB00B5B71Q71', 'U.S._Equity_Index_Fund_9217_GBP_EN_UK.pdf'),
 'Vanguard LifeStrategy 100%': ('GB00B41XG308', 'LifeStrategy_100_Equity_Fund_9232_GBP_EN_UK.pdf'),
 'Aviva Pensions US Equity S6': ('GB00B0ZY5X49', None)}
ALIAS = {'NVIDIA': 'Nvidia', 'Amazon.com': 'Amazon', 'Taiwan Semiconductor Manufacturing': 'TSMC', 'Meta Platforms': 'Meta Platforms',
 'JPMorgan Chase &': 'JPMorgan Chase', 'JPMorgan Chase & Co': 'JPMorgan Chase', 'HSBC Holdings': 'HSBC', 'Shell': 'Shell', 'Unilever': 'Unilever',
 'Alphabet': 'Alphabet', 'Berkshire Hathaway': 'Berkshire Hathaway', 'Samsung Electronics': 'Samsung Electronics'}
def clean(n):
    n = re.sub(r'\s+', ' ', n).strip()
    n = re.sub(r'\s+Class [A-Z]\b.*$', '', n)
    n = re.sub(r'[.,]', ' ', n); n = re.sub(r'\s+', ' ', n).strip()
    for _ in range(3):
        n = re.sub(r'\s+(Inc|Corp|Corporation|Co|Ltd|Limited|plc|PLC|SA|AG|NV|SE|ASA|Holdings? Plc|Company)$', '', n).strip()
    n = n.replace('Amazon com', 'Amazon.com')
    return ALIAS.get(n, n)
def get(u, binary=False):
    b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
    return b if binary else b.decode('utf-8', 'replace')
def txt(h): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'(?s)<script.*?</script>|<style.*?</style>', ' ', h))))
def pdf_text(name):
    open('/tmp/f.pdf', 'wb').write(get('https://fund-docs.vanguard.com/' + name, True))
    return subprocess.run(['pdftotext', '-layout', '/tmp/f.pdf', '-'], capture_output=True, text=True, check=True).stdout
problems, notes = [], []
def ok(cond, what):
    if not cond: problems.append(what)
    return cond
data = json.load(open(FUNDS_PATH)); old = copy.deepcopy(data)
fid = json.load(open(FID_PATH)) if FID_PATH else {}
today = datetime.date.today().isoformat()
src = {}
for name, (isin, pdf) in F.items():
    f = data['funds'].setdefault(name, {})
    # ---- Fidelity / Morningstar: industries, size, top 10, holdings count
    r = fid.get(isin, {})
    asof = r.get('asof', '')
    s = r.get('sectors') or {}
    if ok(len(s) >= 6 and 95 <= sum(s.values()) <= 101, f'{name}: industries not read'):
        f['sectors'] = dict(sorted(s.items(), key=lambda x: -x[1])); f.pop('sectors_note', None)
    z = r.get('size')
    if ok(bool(z) and 95 <= sum(z.values()) <= 102, f'{name}: company size not read'):
        f['size'] = {k: round(v, 1) for k, v in z.items()}
    if name != 'Vanguard LifeStrategy 100%':
        t = {}
        for n, c, w in r.get('top') or []: t[clean(n)] = round(t.get(clean(n), 0) + w, 3)
        if ok(len(t) >= 5 and all(0 < v < 25 for v in t.values()), f'{name}: top companies not read'):
            f['top'] = dict(sorted(t.items(), key=lambda x: -x[1]))
    if name in ('Aviva Pensions US Equity S6', 'Vanguard LifeStrategy 100%'):
        RM = {'United States': 'United States', 'United Kingdom': 'United Kingdom', 'Japan': 'Japan', 'Canada': 'Other developed',
              'Australasia': 'Other developed', 'Asia - Developed': 'Other developed', 'Eurozone': 'Europe (ex UK)', 'Europe - ex Euro': 'Europe (ex UK)',
              'Europe - Emerging': 'Emerging markets', 'Asia - Emerging': 'Emerging markets', 'Latin America': 'Emerging markets',
              'Middle East': 'Emerging markets', 'Africa': 'Emerging markets'}
        g = {}
        for k, v in (r.get('regions') or {}).items(): g[RM.get(k, 'Other developed')] = round(g.get(RM.get(k, 'Other developed'), 0) + v, 2)
        if ok(bool(g) and 80 <= sum(g.values()) <= 101, f'{name}: regions not read'):
            f['countries'] = dict(sorted(g.items(), key=lambda x: -x[1])); f['countries_src'] = f'Fidelity (Morningstar data), {asof} (by region)'
    # ---- Vanguard factsheet PDF: countries / regions, charge, yield, number of holdings
    if pdf:
        try:
            T = pdf_text(pdf)
            m = re.search(r'Ongoing Charges Figure(?: \(OCF\d?\))?\S*\s+(\d+\.\d+)%', T)
            if ok(m and 0 < float(m[1]) < 2, f'{name}: charge not read'): f['ocf'] = float(m[1])
            m = re.search(r'Quoted Historic Yield\s+(\d+\.\d+)%', T)
            if m: f['yield'] = float(m[1])
            m = re.search(r'Number of stocks\s+([\d,]+)', T)
            if m: f['holdings'] = int(m[1].replace(',', ''))
            dm = re.search(r'(?:Factsheet \||As at) (\d{1,2} \w+ \d{4})', T); pdate = dm[1] if dm else ''
            if 'LifeStrategy' in pdf: pass
            else:
                i = T.find('Market allocation'); j = T.find('Source: Vanguard', i)
                c = {}
                if i >= 0 and j > i:
                    for k, v in re.findall(r'([A-Z][A-Za-z .&-]*?[a-z])\s+(\d+\.\d)%?', T[i + 17:j]):
                        k = {'Korea': 'South Korea', 'U.K.': 'United Kingdom'}.get(k.strip(), k.strip())
                        if k != 'Other': c[k] = float(v)
                if ok(len(c) >= 1 and 60 <= sum(c.values()) <= 101, f'{name}: countries not read'):
                    f['countries'] = dict(sorted(c.items(), key=lambda x: -x[1])); f['countries_src'] = f'Vanguard factsheet, {pdate} (top {len(c)} countries)'
            src['pdf'] = pdate
        except Exception as e: problems.append(f'{name}: Vanguard factsheet not read ({e})')
    if asof: src['fid'] = asof
# ---- LifeStrategy look-through: its underlying funds (FT) x each fund's top 10 companies (FT)
def ft_top(isin):
    t = txt(get(f'https://markets.ft.com/data/funds/tearsheet/holdings?s={isin}:GBP'))
    i = t.find('Long allocation', t.find('Top 10 holdings')); j = t.find('Top 10 holdings', i + 20)
    seg = t[i + len('Long allocation'):(j if j > 0 else i + 3000)]
    return [(n.strip(), sym, float(w)) for n, sym, w in re.findall(r'(.+?) ([A-Z0-9.]+:[A-Z]{2,4}) (?:[+-]?\d+\.\d+%|--) (\d+\.\d+)%', seg)][:10]
try:
    funds = [(n, sym.split(':')[0], w) for n, sym, w in ft_top('GB00B41XG308') if re.match(r'^[A-Z]{2}[A-Z0-9]{9}\d$', sym.split(':')[0])]
    look, covered = {}, 0
    for n, isin, w in funds:
        for cn, _, cw in ft_top(isin):
            look[clean(cn)] = look.get(clean(cn), 0) + w / 100 * cw
        covered += w
    look = dict(sorted(((k, round(v, 3)) for k, v in look.items()), key=lambda x: -x[1])[:10])
    if ok(len(funds) >= 4 and covered > 90 and len(look) >= 5, 'LifeStrategy look-through not worked out'):
        f = data['funds']['Vanguard LifeStrategy 100%']; f['top'] = look; f.pop('top_via', None)
        f['top_note'] = 'Worked out from the top 10 companies of each fund LifeStrategy holds (FT data)'
except Exception as e: problems.append(f'LifeStrategy look-through: {e}')
data['sources'] = (f"Industries, company size and biggest holdings: Fidelity (Morningstar data), {src.get('fid', '?')}. "
                   f"Countries, regions and charges: Vanguard factsheets, {src.get('pdf', '?')}. LifeStrategy's biggest companies: FT. "
                   "Aviva charge: your plan's charge from your Aviva account (fixed figure). Updated automatically each month.")
data['updated'] = today
changed = [n for n in data['funds'] if data['funds'][n] != old['funds'].get(n)]
json.dump(data, open(FUNDS_PATH, 'w'), indent=1, ensure_ascii=False)
print('Funds changed:', changed or 'none')
for n in F: print(' ', n, json.dumps({k: data['funds'][n].get(k) for k in ('countries', 'top', 'size', 'ocf')}, ensure_ascii=False)[:600])
if problems:
    print('PROBLEMS (last good figures kept for these):'); [print(' -', p) for p in problems]; sys.exit(1)
