import csv, sys, os, re
from datetime import datetime

def fit(t, y):
    n=len(t); mt=sum(t)/n; my=sum(y)/n
    sxx=sum((x-mt)**2 for x in t); sxy=sum((t[i]-mt)*(y[i]-my) for i in range(n))
    m=sxy/sxx; b=my-m*mt
    res=[y[i]-(m*t[i]+b) for i in range(n)]
    sse=sum(r*r for r in res); sst=sum((v-my)**2 for v in y)
    se=(sse/(n-2)/sxx)**0.5
    return m, se, (1-sse/sst if sst else float('nan'))

def report(label, t, prod, sett):
    lag=[prod[i]-sett[i] for i in range(len(t))]
    print(f"\n=== {label}  ({len(t)} samples, {(t[-1]-t[0])/60:.2f} h)")
    for nm,y in (("produced",prod),("settled",sett),("lag",lag)):
        m,se,r2=fit(t,y)
        print(f"  {nm:9s} {m:+8.4f} +/- {se:.4f} blk/min   R2={r2:.4f}")
    span=t[-1]-t[0]
    print(f"  lag start {lag[0]:.0f} end {lag[-1]:.0f} min {min(lag):.0f} max {max(lag):.0f}"
          f"  sawtooth {max(lag)-min(lag):.0f}")
    print(f"  endpoint estimate {(lag[-1]-lag[0])/span:+.4f} blk/min  <-- method being replaced")

B=os.path.expanduser("~/AppChain/experiments/baseline")
def col(p):
    with open(p) as f: return [(float(r["timestamp"]), float(r["value"])) for r in csv.DictReader(f)]
pr=col(f"{B}/blocks_produced.csv"); se_=col(f"{B}/blocks_settled.csv")
d=dict(se_); pairs=[(ts,v,d[ts]) for ts,v in pr if ts in d]
report("baseline 15 h, no load (04/08)", [p[0]/60 for p in pairs],
       [p[1] for p in pairs], [p[2] for p in pairs])

pat=re.compile(r'(\d{4}-\d\d-\d\dT[\d:]+Z)\s+produced=(\d+)\s+settled=(\d+)')
for r in ("r3","r4"):
    p=os.path.expanduser(f"~/AppChain/patrol_{r}_trace.log")
    if not os.path.exists(p): print(f"\n=== patrol-{r}: no trace file"); continue
    rows=[]
    for line in open(p, errors="replace"):
        m=pat.search(line)
        if m: rows.append((datetime.strptime(m.group(1),"%Y-%m-%dT%H:%M:%SZ").timestamp()/60,
                           float(m.group(2)), float(m.group(3))))
    if len(rows)<5: print(f"\n=== patrol-{r}: only {len(rows)} parsed rows"); continue
    report(f"patrol-{r}, 0.4 tx/s (20/08)", [x[0] for x in rows],
           [x[1] for x in rows], [x[2] for x in rows])
