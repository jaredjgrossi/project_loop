import pickle, statistics as st, collections, datetime, sys
res = pickle.load(open(sys.argv[1], "rb"))
def is_run(r): return 2.2 <= r["mps"] <= 6.5 and 0.8 <= r["miles"] <= 30
runs = [r for r in res if is_run(r)]
print("routes parsed", len(res), "| classified as runs", len(runs))
byy = collections.defaultdict(list)
for r in runs: byy[r["date"][:4]].append(r)
print("\nyear  n   med_mi  med_min  turns/mi  retrace  out&back>0.5")
for y in sorted(byy):
    v = byy[y]
    print(y, len(v), round(st.median(r["miles"] for r in v),2), round(st.median(r["minutes"] for r in v),1),
          round(st.median(r["turns_per_mile"] for r in v),2), round(st.median(r["retrace_frac"] for r in v),2),
          round(sum(r["out_and_back"]>0.5 for r in v)/len(v),2))
cut = "2025-10-30"
rec = [r for r in runs if r["date"] >= cut]
print("\nLAST 12 MONTHS:", len(rec), "runs")
miles = sorted(r["miles"] for r in rec)
q = lambda p: miles[int(p*(len(miles)-1))]
print("miles p10/p50/p90/max:", q(.1), q(.5), q(.9), miles[-1])
print("turns/mile p10/p50/p90:", *[sorted(r['turns_per_mile'] for r in rec)[int(p*(len(rec)-1))] for p in (.1,.5,.9)])
print("closure<400m (loop-ish):", round(sum(r["closure_m"]<400 for r in rec)/len(rec),2),
      "| out&back>0.5:", round(sum(r["out_and_back"]>0.5 for r in rec)/len(rec),2),
      "| retrace>0.3:", round(sum(r["retrace_frac"]>0.3 for r in rec)/len(rec),2))
# start clusters
sc = collections.Counter(r["start_cell"] for r in rec)
print("distinct start cells (300m):", len(sc), "| top3 share:", [round(c/len(rec),2) for _,c in sc.most_common(3)])
# habitual routes: Jaccard of 50m cell sets
def jac(a,b): return len(a&b)/len(a|b)
home = [r for r in rec if r["start_cell"] == sc.most_common(1)[0][0]]
print("runs from most common start:", len(home))
groups=[]
for r in home:
    for g in groups:
        if jac(r["cells"], g[0]["cells"]) >= 0.6: g.append(r); break
    else: groups.append([r])
groups.sort(key=len, reverse=True)
print("distinct route 'families' (Jaccard>=0.6):", len(groups))
for g in groups[:6]:
    print("  family of", len(g), "runs | median mi", round(st.median(x["miles"] for x in g),2), "| turns/mi", round(st.median(x["turns_per_mile"] for x in g),2),
          "| out&back", round(st.median(x["out_and_back"] for x in g),2), "| closure_m", round(st.median(x["closure_m"] for x in g)))
share_top3 = sum(len(g) for g in groups[:3])/len(home)
print("top-3 families cover", round(share_top3,2), "of runs from home start")
