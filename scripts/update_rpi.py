"""Update rpi.json with September RPI figures (ONS series CHAW).
Used to estimate deferred defined-benefit pensions revalued by RPI.
Public data only. Never fails the job: if ONS can't be read or the numbers
look wrong, the existing file is kept and a warning is printed."""
import csv, io, json, sys, urllib.request, datetime
path = sys.argv[1] if len(sys.argv) > 1 else 'rpi.json'
try:
    old = json.load(open(path))
except Exception:
    old = {"series": "CHAW", "sep": {}}
url = "https://www.ons.gov.uk/generator?format=csv&uri=/economy/inflationandpriceindices/timeseries/chaw/mm23"
try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (wealth page RPI update)"})
    text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    sep = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[0].strip().endswith(" SEP"):
            y = row[0].strip()[:4]
            try: sep[y] = float(row[1])
            except ValueError: pass
    years = sorted(sep)
    if len(years) < 10: raise ValueError("too few September values")
    for a, b in zip(years, years[1:]):
        if not (0.85 < sep[b] / sep[a] < 1.25): raise ValueError("implausible jump %s-%s" % (a, b))
    for y, v in old.get("sep", {}).items():
        if y in sep and abs(sep[y] - v) > 0.5: raise ValueError("published value for %s changed a lot" % y)
    if sep != old.get("sep"):
        json.dump({"series": "CHAW", "source": "ONS", "sep": sep, "updated": datetime.date.today().isoformat()},
                  open(path, "w"), indent=1)
        print("rpi.json updated, latest September:", years[-1])
    else:
        print("rpi.json unchanged")
except Exception as e:
    print("WARNING: RPI not updated:", e)
