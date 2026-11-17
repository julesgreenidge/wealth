// Reads Fidelity's fund "portfolio" pages (Morningstar data) with a hidden browser,
// because those figures load after the page opens. Writes raw figures to a JSON file.
const { chromium } = require('playwright');
const fs = require('fs');
const ISINS = (process.argv[3] || 'GB00BD3RZ582,GB00B5B71Q71,GB00B41XG308,GB00B0ZY5X49').split(',');
const SECT = {'Basic materials':'Basic materials','Con cyclical':'Consumer cyclical','Financial svs':'Financial services','Real estate':'Real estate',
  'Comm services':'Communication services','Energy':'Energy','Industrials':'Industrials','Technology':'Technology',
  'Con defensive':'Consumer defensive','Healthcare':'Healthcare','Utilities':'Utilities'};
const num = s => parseFloat(String(s).replace(/[%,]/g, ''));
(async () => {
  const out = {}; const b = await chromium.launch();
  for (const isin of ISINS) {
    const r = { ok: false };
    try {
      const p = await b.newPage({ userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36' });
      await p.goto(`https://www.fidelity.co.uk/factsheet-data/factsheet/${isin}/portfolio`, { waitUntil: 'networkidle', timeout: 90000 }).catch(() => {});
      await p.waitForSelector('text=Stock sectors', { timeout: 30000 }).catch(() => {});
      await p.waitForTimeout(2000);
      const L = (await p.evaluate(() => document.body.innerText)).split('\n').map(s => s.trim()).filter(Boolean);
      await p.close();
      const at = w => L.indexOf(w);
      // as-of date
      const asof = L.find(l => /^Portfolio as of /.test(l)); if (asof) r.asof = asof.replace('Portfolio as of ', '');
      // sectors
      let i = at('Stock sectors');
      if (i >= 0) { r.sectors = {}; for (let j = i; j < Math.min(L.length - 1, i + 60); j++) if (SECT[L[j]] && /%$/.test(L[j + 1])) r.sectors[SECT[L[j]]] = num(L[j + 1]); }
      // size (style box: Large/Medium/Small rows of three numbers)
      i = at('Stock style');
      if (i >= 0) { const row = n => { const k = L.indexOf(n, i); return k < 0 ? null : [1, 2, 3].map(d => num(L[k + d])).reduce((a, c) => a + c, 0) };
        const s = { Large: row('Large'), Medium: row('Medium'), Small: row('Small') }; if (Object.values(s).every(v => v != null && !isNaN(v))) r.size = s; }
      // top 10 holdings
      r.top = L.filter(l => /^\d+\t/.test(l)).map(l => l.split('\t')).filter(c => c.length >= 5).map(c => [c[1], c[3], num(c[4])]);
      // regions
      i = at('Continent or country allocation (%)');
      if (i >= 0) { const vals = []; let j = i + 1; while (/^[\d.]+$/.test(L[j])) { const s = L[j]; vals.push(num(s.slice(0, s.length / 2))); j++ }
        r.regions = {}; vals.forEach((v, k) => r.regions[L[j + k]] = v); }
      const h = L.indexOf('Total no. of equity holdings'); if (h >= 0) r.holdings = num(L[h + 1]);
      r.ok = !!(r.sectors && Object.keys(r.sectors).length);
    } catch (e) { r.error = String(e) }
    out[isin] = r; console.log(isin, r.ok ? 'read' : 'NOT read', r.error || '');
  }
  await b.close(); fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
})();
