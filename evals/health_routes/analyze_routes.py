import csv, math, os, re, sys, calendar, pickle
from multiprocessing import Pool

PT = re.compile(r'<trkpt lon="([^"]+)" lat="([^"]+)">.*?<time>([^<]+)</time>', re.S)
M_LAT = 111_320.0
M_LON = M_LAT * math.cos(math.radians(40.75))

def xy(lon, lat):
    return lon * M_LON, lat * M_LAT

def pt(s):
    return calendar.timegm((int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19])))

def resample(pts, step=25.0):
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0]-out[-1][0], p[1]-out[-1][1]) >= step:
            out.append(p)
    return out

def analyze(path):
    name = os.path.basename(path)
    try:
        txt = open(path, encoding="utf-8").read()
    except Exception:
        return None
    m = PT.findall(txt)
    if len(m) < 20:
        return None
    pts = [xy(float(a), float(b)) for a, b, _ in m]
    ts = [pt(t) for _, _, t in m]
    dist = sum(math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1]) for i in range(1, len(pts)))
    dur = ts[-1] - ts[0]
    if dur <= 0 or dist < 500:
        return None
    rs = resample(pts)
    n = len(rs)
    if n < 8:
        return None
    br = lambda a, b: math.degrees(math.atan2(b[0]-a[0], b[1]-a[1])) % 360
    brg = [br(rs[i], rs[i+2]) for i in range(n-2)]
    turns, last = 0, -10
    for i in range(1, len(brg)-2):
        dh = abs((brg[i+2]-brg[i-1]+180) % 360 - 180)
        if dh >= 60 and i-last >= 3:
            turns += 1; last = i
    miles = dist/1609.34
    cell = 30.0
    seen, retr = {}, 0
    for i, (x, y) in enumerate(rs):
        c = (int(x//cell), int(y//cell))
        if c in seen and i-seen[c] > 12: retr += 1
        seen.setdefault(c, i)
    half = n//2
    first = {(int(x//cell), int(y//cell)) for x, y in rs[:half]}
    second = [(int(x//cell), int(y//cell)) for x, y in rs[half:]]
    oab = sum(1 for c in second if c in first)/max(1, len(second))
    cells = {(int(x//50), int(y//50)) for x, y in rs}
    sx, sy = pts[0]
    return {"file": name, "date": name.split("_")[1], "start_epoch": ts[0], "miles": round(miles, 2),
            "minutes": round(dur/60, 1), "mps": round(dist/dur, 2), "turns_per_mile": round(turns/miles, 2),
            "retrace_frac": round(retr/n, 3), "closure_m": round(math.hypot(pts[0][0]-pts[-1][0], pts[0][1]-pts[-1][1])),
            "out_and_back": round(oab, 3), "start_cell": f"{int(sx//300)}_{int(sy//300)}", "cells": cells}

if __name__ == "__main__":
    d, out = sys.argv[1], sys.argv[2]
    files = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".gpx"))
    with Pool(4) as p:
        res = [r for r in p.imap(analyze, files, chunksize=8) if r]
    pickle.dump(res, open(out + ".pkl", "wb"))
    cols = [k for k in res[0] if k != "cells"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in res: w.writerow({k: r[k] for k in cols})
    print(len(files), "files;", len(res), "parsed")
