"""Check UK tax and pension figures on GOV.UK and update rules.json.
Public figures only. If any figure can't be read confidently, the file is
left unchanged and the job fails, so GitHub emails the owner."""
import html, json, re, sys, urllib.request, datetime
PATH = sys.argv[1] if len(sys.argv) > 1 else 'rules.json'
DEBUG = '--debug' in sys.argv
def text(slug):
    req = urllib.request.Request('https://www.gov.uk/api/content/' + slug, headers={'User-Agent': 'wealth-page rules check'})
    d = json.load(urllib.request.urlopen(req, timeout=60))
    det = d.get('details', {})
    parts = [det.get('body') or '']
    for p in det.get('parts', []) or []:
        parts.append(p.get('body') or '')
    h = ' '.join(x if isinstance(x, str) else ' '.join(y.get('content', '') for y in x) for x in parts)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', h))
    return re.sub(r'\s+', ' ', t)
def num(s): return float(s.replace(',', ''))
def show(t, words):
    for w in words:
        for m in re.finditer(w, t):
            print('  ...' + t[max(0, m.start()-150):m.end()+200] + '...')
            break
problems, new = [], {}
try:
    t = text('income-tax-rates')
    if DEBUG: print('income-tax-rates:'); show(t, ['Personal Allowance', 'Basic rate', 'Higher rate', 'Additional rate', '£1 for every £2'])
    pa = re.search(r'Personal Allowance\s+Up to £([\d,]+)\s+0\s?%', t)
    br = re.search(r'Basic rate\s+£([\d,]+) to £([\d,]+)\s+(\d+)\s?%', t)
    hr = re.search(r'Higher rate\s+£([\d,]+) to £([\d,]+)\s+(\d+)\s?%', t)
    ar = re.search(r'Additional rate\s+(?:over|above) £([\d,]+)\s+(\d+)\s?%', t)
    tp = re.search(r'£1 for every £2[^£]{0,60}(?:above|over) £([\d,]+)', t)
    if not all([pa, br, hr, ar, tp]): problems.append('income tax figures not found')
    else:
        P = num(pa[1]); new['income_tax'] = {'pa': P, 'basic_to': num(br[2]), 'higher_to': num(hr[2]),
            'rates': [num(br[3]), num(hr[3]), num(ar[2])], 'taper_from': num(tp[1])}
except Exception as e: problems.append('income tax page: %s' % e)
try:
    t = text('new-state-pension/what-youll-get')
    if DEBUG: print('state pension:'); show(t, ['per week', 'a week', 'State Pension is'])
    m = re.search(r'full (?:rate of )?(?:the )?(?:new )?State Pension[^£]{0,40}£([\d.,]+) (?:per|a) week', t)
    if not m: problems.append('State Pension figure not found')
    else: new['state_pension_week'] = num(m[1])
except Exception as e: problems.append('State Pension page: %s' % e)
try:
    t = text('tax-on-pension')
    if DEBUG: print('tax-on-pension:'); show(t, ['tax-free', 'lump sum allowance', 'Lump Sum Allowance'])
    vals = [num(x) for x in re.findall(r'£([\d,]{7,})', t) if 150000 <= num(x) <= 600000]
    m = re.search(r'(?:up to|maximum (?:of)?|most you can take[^£]{0,40}is) £([\d,]+)', t)
    lsa = num(m[1]) if m and 150000 <= num(m[1]) <= 600000 else (vals[0] if len(set(vals)) == 1 else None)
    if lsa is None: problems.append('Lump Sum Allowance not found')
    else: new['lsa'] = lsa
except Exception as e: problems.append('pension tax page: %s' % e)
old = {}
try: old = json.load(open(PATH))
except Exception: pass
# sanity checks against the last good figures
def far(a, b, pct): return b and abs(a - b) / b > pct
it, oit = new.get('income_tax'), old.get('income_tax', {})
if it:
    if not (8000 < it['pa'] < 25000 and it['pa'] < it['basic_to'] < it['higher_to'] < 250000 and 10 <= it['rates'][0] < it['rates'][1] < it['rates'][2] <= 60):
        problems.append('income tax figures look wrong: %s' % it)
    for k in ('pa', 'basic_to', 'higher_to', 'taper_from'):
        if oit.get(k) and far(it[k], oit[k], 0.25): problems.append('%s changed by more than 25%%' % k)
if new.get('state_pension_week') and old.get('state_pension_week') and far(new['state_pension_week'], old['state_pension_week'], 0.15):
    problems.append('State Pension changed by more than 15%')
if new.get('lsa') and old.get('lsa') and far(new['lsa'], old['lsa'], 0.25):
    problems.append('Lump Sum Allowance changed by more than 25%')
if problems:
    print('NOT UPDATED. Problems:'); [print(' -', p) for p in problems]
    sys.exit(1)
today = datetime.date.today()
ty = today.year if (today.month, today.day) >= (4, 6) else today.year - 1
out = dict(old)
out.update(new)
out['tax_year'] = '%d/%02d' % (ty, (ty + 1) % 100)
out['checked'] = today.isoformat()
out.setdefault('pension_access', [{'from': '2000-01-01', 'age': 55}, {'from': '2028-04-06', 'age': 57}])
json.dump(out, open(PATH, 'w'), indent=1)
changed = {k: (old.get(k), new[k]) for k in new if old.get(k) != new[k]}
print('rules.json checked for', out['tax_year'], '- changed:', changed or 'nothing')
