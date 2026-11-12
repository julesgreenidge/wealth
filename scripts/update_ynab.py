"""Daily: read Jules's YNAB budget through the YNAB API (token from the YNAB_TOKEN secret),
build the net worth / cash flow / spending figures and seal them with the public key in lock.json.
Only the sealed file (ynab.enc) is written. Nothing financial is ever printed: this repo's logs are public."""
import os, sys, re, json, base64, datetime as dt, urllib.request
import pandas as pd

def atype(a):
    if re.search(r'Pension|SIPP', a): return 'Pensions'
    if re.search(r'S&S ISA', a): return 'Stocks & shares ISAs'
    if re.search(r'Cash ISA', a): return 'Cash ISAs'
    if re.search(r'Crypto|Coinbase|Electrum|Ledger|Solflare', a): return 'Crypto'
    if re.search(r'GIA|Freetrade', a): return 'Shares (GIA)'
    if re.search(r'P2P|Lending', a): return 'Other assets'
    if re.search(r'Borrowing', a): return 'Loans'
    if re.search(r'Credit Card|AMEX', a): return 'Credit cards'
    if re.search(r'Saving|Saver|Bonds|Marcus|Roundup', a): return 'Cash savings'
    return 'Current accounts'
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
                accounts=[dict(name=a.Account, type=a.type, balance=round(float(a.balance), 2), updated=str(a.updated.date())) for a in bal.itertuples()])

def from_api(token):
    def get(path):
        req = urllib.request.Request('https://api.ynab.com/v1/budgets/last-used' + path, headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=60) as resp: return json.load(resp)['data']
    cats = {}
    for g in get('/categories')['category_groups']:
        for c in g['categories']:
            group = 'Hidden Categories' if (c.get('hidden') or g.get('hidden')) else g['name']
            name = c['name']
            if g['name'] == 'Internal Master Category' and name.startswith('Inflow'): group, name = 'Inflow', 'Ready to Assign'
            cats[c['id']] = (group, name)
    accounts = {a['id']: a['name'] for a in get('/accounts')['accounts'] if not a.get('deleted')}
    rows = []
    for t in get('/transactions')['transactions']:
        if t.get('deleted') or t['account_id'] not in accounts: continue
        base = dict(Account=accounts[t['account_id']], date=t['date'], Payee=t.get('payee_name') or '')
        subs = [s for s in (t.get('subtransactions') or []) if not s.get('deleted')]
        for s in (subs or [t]):
            g, n = cats.get(s.get('category_id'), (None, None))
            if s.get('transfer_account_id'): g = n = None
            rows.append(dict(base, **{'Category Group': g, 'Category': n, 'net': s['amount'] / 1000}))
    df = pd.DataFrame(rows); df['date'] = pd.to_datetime(df.date)
    return df

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
    data = build(from_api(token), today)
    seal(data, 'lock.json', 'ynab.enc')
    print('YNAB figures sealed into ynab.enc.')   # deliberately no numbers: logs are public
