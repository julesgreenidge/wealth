import re, html, urllib.request
ISINS = {'GAC': 'GB00BD3RZ582', 'USEQ': 'GB00B5B71Q71', 'LS100': 'GB00B41XG308', 'AVUSEQ': 'GB00B0ZY5X49'}
def get(u):
    r = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'})
    return urllib.request.urlopen(r, timeout=60).read().decode('utf-8', 'replace')
def txt(h): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'(?s)<script.*?</script>|<style.*?</style>', ' ', h))))
for k, i in ISINS.items():
    for page in ['holdings', 'summary']:
        u = f'https://markets.ft.com/data/funds/tearsheet/{page}?s={i}:GBP'
        try:
            t = txt(get(u)); print('=====', k, page, len(t))
            for w in ['Top 5 regions', 'Top 5 sectors', 'Top 10 holdings', 'Region', 'Sector', 'Ongoing charge', 'Asset type', 'Market cap', 'Giant', 'Large']:
                m = t.find(w)
                if m >= 0: print('  [' + w + ']', t[m:m+420])
        except Exception as e: print('=====', k, page, 'ERROR', e)
