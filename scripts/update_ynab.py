"""Daily: read the YNAB budget through the YNAB API (token from the YNAB_TOKEN secret),
build the net worth / cash flow / spending figures and seal them with the public key in lock.json.
Only the sealed file (ynab.enc) is written. Nothing financial is ever printed: this repo's logs are public."""
import os, sys, re, json, base64, datetime as dt, urllib.request
import pandas as pd

def atype(a):
    if re.search(r'Pension|SIPP|Legal & General', a): return 'Pensions'
    if re.search(r'S&S ISA', a): return 'Stocks & shares ISAs'
    if re.search(r'Cash ISA', a): return 'Cash ISAs'
    if re.search(r'Crypto|Coinbase|Electrum|Ledger|Solflare', a): return 'Crypto'
    if re.search(r'GIA|Freetrade', a): return 'Shares (GIA)'
    if re.search(r'P2P|Lending', a): return 'Other assets'
    if re.search(r'Borrowing', a): return 'Loans'
    if re.search(r'Credit Card|AMEX', a): return 'Credit cards'
    if re.search(r'Saving|Saver|Bonds|Marcus|Roundup', a): return 'Cash savings'
    return 'Current accounts'   # no name pattern matched: flagged as a guess on the page
def guessed(a):
    return atype(a) == 'Current accounts' and not re.search(r'Current|Monzo|Starling|Revolut|Chase|Barclays|Lloyds|HSBC|Nationwide|NatWest|Santander|Halifax|First Direct|Cash|Wallet|Joint', a, re.I)
ONB = {'Current accounts', 'Credit cards', 'Cash savings', 'Cash ISAs'}

def build(r, cutoff):
    """r: columns Account, date, Payee, Category Group, Category, net"""
    r = r[(r.date <= cutoff) & ~r.Account.str.contains('JISA')].copy()
    r['Category Group/Category'] = r['Category Group'].fillna('') + ': ' + r['Category'].fillna('')
    r['type'] = r.Account.map(atype)
    r['month'] = r.date.dt.to_period('M')
    months = pd.period_range(r.month.min(), cutoff.to_period('M'), freq='M')
    bt = r.pivot_table(index='month', columns='type', values='net', aggfunc='sum').reindex(months).fillna(0).cumsum()
    bt.index = bt.index.astype(str); nw = bt.sum(axis=1)
    gains = r[r.Payee.fillna('').str.startswith('Investment Gains')].groupby('month').net.sum()
    inc = r[(r.type.isin(ONB)) & (r.Category == 'Ready to Assign')].groupby('month').net.sum()
    sp = r[(r.type.isin(ONB)) & r['Category Group'].notna() & ~r['Category Group'].isin(['Inflow', 'Savings'])]
    spend = -sp.groupby('month').net.sum()
    cf = pd.DataFrame({'income': inc, 'spending': spend, 'growth': gains}).reindex(months).fillna(0); cf.index = cf.index.astype(str)
    grp = (-sp.pivot_table(index='month', columns='Category Group', values='net', aggfunc='sum')).reindex(months).fillna(0); grp.index = grp.index.astype(str)
    cat = (-sp.pivot_table(index='month', columns='Category Group/Category', values='net', aggfunc='sum')).reindex(months).fillna(0); cat.index = cat.index.astype(str)
    bal = r.groupby(['Account', 'type']).agg(balance=('net', 'sum'), updated=('date', 'max')).reset_index()
    bal = bal[bal.balance.abs() > 0.5].sort_values('balance', ascending=False)
    rd = lambda s: [round(float(v), 2) for v in s]
    return dict(cutoff=str(cutoff.date()), months=list(bt.index), nw=rd(nw),
                bytype={c: rd(bt[c]) for c in bt.columns}, cf={k: rd(cf[k]) for k in cf.columns},
                groups={c: rd(grp[c]) for c in grp.columns},
                cats={c: rd(cat[c]) for c in cat.columns if cat[c].abs().sum() > 0},
                accounts=[dict(name=a.Account, type=a.type, balance=round(float(a.balance), 2), updated=str(a.updated.date()), guess=bool(guessed(a.Account))) for a in bal.itertuples()])

def from_api(token):
    def raw(path):
        req = urllib.request.Request('https://api.ynab.com/v1' + path, headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=60) as resp: return json.load(resp)['data']
    # Always use your own budget, never YNAB's "last used" one (that switches to the Family Budget whenever you last opened it).
    # Your budget = the one whose name doesn't contain "family"; if there are several, the YNAB_BUDGET setting names it.
    want = os.environ.get('YNAB_BUDGET', '').strip().lower()
    budgets = [b for b in raw('/budgets')['budgets'] if (want and b['name'].strip().lower() == want) or (not want and 'family' not in b['name'].lower())]
    print('Budgets matched:', len(budgets))   # count only
    if len(budgets) != 1: sys.exit('Could not pick your own YNAB budget: ' + ('none' if not budgets else 'several') + ' matched. Set YNAB_BUDGET to its name.')
    B = '/budgets/' + budgets[0]['id']
    get = lambda path: raw(B + path)
    cats, emerg = {}, []
    for g in get('/categories')['category_groups']:
        for c in g['categories']:
            group = 'Hidden Categories' if (c.get('hidden') or g.get('hidden')) else g['name']
            name = c['name']
            if g['name'] == 'Internal Master Category' and name.startswith('Inflow'): group, name = 'Inflow', 'Ready to Assign'
            cats[c['id']] = (group, name)
            if 'emergency' in c['name'].lower() and not (c.get('hidden') or c.get('deleted')): emerg.append(c.get('balance', 0) / 1000)
    accounts = {a['id']: a['name'] for a in get('/accounts')['accounts'] if not a.get('deleted')}
    rows = []
    for t in get('/transactions?since_date=2000-01-01')['transactions']:
        if t.get('deleted') or t['account_id'] not in accounts: continue
        base = dict(Account=accounts[t['account_id']], date=t['date'], Payee=t.get('payee_name') or '',
                    Flag=t.get('flag_name') or '', Memo=t.get('memo') or '',
                    Tags=' '.join((x.get('name') or '') if isinstance(x, dict) else str(x) for x in (t.get('tags') or [])))
        subs = [s for s in (t.get('subtransactions') or []) if not s.get('deleted')]
        for s in (subs or [t]):
            g, n = cats.get(s.get('category_id'), (None, None))
            if s.get('transfer_account_id'): g = n = None
            rows.append(dict(base, **{'Category Group': g, 'Category': n, 'net': s['amount'] / 1000,
                                      'Memo': ' '.join(filter(None, [base['Memo'], s.get('memo') if s is not t else None]))}))
    df = pd.DataFrame(rows); df['date'] = pd.to_datetime(df.date)
    print('Transactions from', df.date.min().year, 'to', df.date.max().year)   # years only, no figures
    df.attrs['emergency'] = round(sum(emerg), 2) if emerg else None   # money available in the Emergency Fund category (ring-fenced in the forecast)
    return df

def family_spending(token, cutoff):
    """Spending by month from the YNAB budget whose name contains 'family' (the joint account), for the Joint spending tab.
    Categorised outflows (refunds net off), excluding transfers and money assigned (Inflow). No balances."""
    H = {'Authorization': 'Bearer ' + token}
    get = lambda p: json.load(urllib.request.urlopen(urllib.request.Request('https://api.ynab.com/v1' + p, headers=H), timeout=60))['data']
    fam = [b for b in get('/budgets')['budgets'] if 'family' in b['name'].lower()]
    if not fam: print('No family budget found.'); return None
    B = '/budgets/' + fam[0]['id']; cats = {}
    for g in get(B + '/categories')['category_groups']:
        for c in g['categories']:
            group = 'Hidden Categories' if (c.get('hidden') or g.get('hidden')) else g['name']
            if g['name'] == 'Internal Master Category': group = 'Inflow'
            cats[c['id']] = (group, c['name'])
    rows = []
    for t in get(B + '/transactions?since_date=2000-01-01')['transactions']:
        if t.get('deleted'): continue
        subs = [x for x in (t.get('subtransactions') or []) if not x.get('deleted')]
        for x in (subs or [t]):
            if x.get('transfer_account_id'): continue
            g, n = cats.get(x.get('category_id'), (None, None))
            if not g or g == 'Inflow': continue
            rows.append(dict(month=t['date'][:7], g=g, c=g + ': ' + n, net=-x['amount'] / 1000))
    if not rows: return None
    df = pd.DataFrame(rows); df = df[df.month <= str(cutoff.date())[:7]]
    months = [str(m) for m in pd.period_range(df.month.min(), cutoff.to_period('M'), freq='M')]
    gp = df.pivot_table(index='month', columns='g', values='net', aggfunc='sum').reindex(months).fillna(0)
    cp = df.pivot_table(index='month', columns='c', values='net', aggfunc='sum').reindex(months).fillna(0)
    rd = lambda s: [round(float(v), 2) for v in s]
    print('Family budget read.')   # no figures
    return dict(months=months, groups={k: rd(gp[k]) for k in gp.columns}, cats={k: rd(cp[k]) for k in cp.columns if cp[k].abs().sum() > 0})

def from_csv(path):
    r = pd.read_csv(path, encoding='utf-8-sig')
    m = lambda s: s.astype(str).str.replace('£', '').str.replace(',', '').astype(float)
    r['net'] = m(r.Inflow) - m(r.Outflow); r['date'] = pd.to_datetime(r.Date, format='%d-%m-%Y')
    return r[['Account', 'date', 'Payee', 'Category Group', 'Category', 'net']]

def seal(obj, lock_path, out):
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pub = load_der_public_key(base64.b64decode(json.load(open(lock_path))['pub']))
    k, iv = AESGCM.generate_key(256), os.urandom(12)
    ct = AESGCM(k).encrypt(iv, json.dumps(obj, separators=(',', ':')).encode(), None)
    ek = pub.encrypt(k, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    b = lambda x: base64.b64encode(x).decode()
    json.dump(dict(v=2, k=b(ek), iv=b(iv), ct=b(ct)), open(out, 'w'))

if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--csv':   # local check: python update_ynab.py --csv register.csv 2026-11-08 out.json
        json.dump(build(from_csv(sys.argv[2]), pd.Timestamp(sys.argv[3])), open(sys.argv[4], 'w')); sys.exit()
    token = os.environ.get('YNAB_TOKEN', '').strip()
    if not token:
        print('No YNAB_TOKEN secret set yet: nothing to do.'); sys.exit(0)
    today = pd.Timestamp(dt.date.today())
    df = from_api(token)
    data = build(df, today); data['emergency'] = df.attrs.get('emergency')
    # ISA allowance used this tax year: money moved into ISAs from non-ISA accounts minus money taken out (Trading 212 ISAs are flexible,
    # so withdrawals give allowance back; the others have no withdrawals). Moves between ISAs, interest, gains and future scheduled items are ignored.
    ty = pd.Timestamp(today.year if (today.month, today.day) >= (4, 6) else today.year - 1, 4, 6)
    i = df[(df.date >= ty) & (df.date <= today) & df.Account.str.contains('ISA') & ~df.Account.str.contains('JISA')
           & df.Payee.str.startswith('Transfer') & ~df.Payee.str.contains('ISA')]
    data['isa_used'] = round(float(i.net.sum()), 2); data['isa_from'] = str(ty.date())
    # Tax items by tax year, from transactions you tag (YNAB flag name, tag or memo; not the category):
    # "Taxed interest" (savings interest; "Untaxed interest" e.g. Premium Bonds is left out) and "Charity" (Gift Aid donations)
    def tagged(word, sign):
        hit = pd.Series(False, index=df.index)
        for col in ('Flag', 'Tags', 'Memo'):
            if col in df: hit |= df[col].astype(str).str.contains(r'(?<![a-z])' + word + r'(?![a-z])', case=False, regex=True)
        x = df[hit & (df.date <= today)].copy()
        x['v'] = x.net * sign
        x['ty'] = x.date.apply(lambda d: d.year if (d.month, d.day) >= (4, 6) else d.year - 1)
        out = {f'{y}/{str(y + 1)[2:]}': dict(total=round(float(g.v.sum()), 2), n=int(len(g)),
               by={k: round(float(v), 2) for k, v in g.groupby('Account').v.sum().items()}) for y, g in x.groupby('ty')}
        where = [c for c in ('Flag', 'Tags', 'Memo') if c in df and df.loc[hit, c].astype(str).str.contains(word, case=False).any()]
        print(f'"{word}" found this tax year:', 'yes' if (x.date >= ty).any() else 'no', '| tagged via:', ', '.join(where) or 'none')  # no amounts
        return out
    data['interest'] = tagged('taxed interest', 1)
    data['charity'] = tagged('charity', -1)
    try: data['family'] = family_spending(token, today)
    except Exception as e: print('Family budget not read:', type(e).__name__)
    seal(data, 'lock.json', 'ynab.enc')
    print('YNAB figures sealed into ynab.enc.')   # deliberately no numbers: logs are public
