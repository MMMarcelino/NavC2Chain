import os, re
from datetime import datetime, timezone

def fit(t, y):
    n=len(t); mt=sum(t)/n; my=sum(y)/n
    sxx=sum((x-mt)**2 for x in t); m=sum((t[i]-mt)*(y[i]-my) for i in range(n))/sxx
    b=my-m*mt; res=[y[i]-(m*t[i]+b) for i in range(n)]
    sse=sum(r*r for r in res); sst=sum((v-my)**2 for v in y)
    return m, (sse/(n-2)/sxx)**0.5, (1-sse/sst if sst else float('nan')), res

pat=re.compile(r'^(\d{4}-\d\d-\d\dT[\d:]+Z)\s+(\d+)\s+(\d+)\s+(-?\d+)\s*$')
for r in ("r3","r4"):
    p=os.path.expanduser(f"~/AppChain/patrol_{r}_trace.log")
    rows=[]
    for line in open(p, errors="replace"):
        m=pat.match(line.strip())
        if m:
            ts=datetime.strptime(m.group(1),"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            rows.append((ts.timestamp()/60, float(m.group(2)), float(m.group(3))))
    if len(rows)<5:
        print(f"patrol-{r}: only {len(rows)} rows parsed"); continue
    rows.sort()
    t=[x[0] for x in rows]; prod=[x[1] for x in rows]; sett=[x[2] for x in rows]
    lag=[prod[i]-sett[i] for i in range(len(t))]
    print(f"\n=== patrol-{r}  {len(t)} samples, {(t[-1]-t[0]):.0f} min, "
          f"step {(t[1]-t[0])*60:.0f} s")
    for nm,y in (("produced",prod),("settled",sett),("lag",lag)):
        m,se,r2,_=fit(t,y)
        print(f"  {nm:9s} {m:+8.4f} +/- {se:.4f} blk/min   R2={r2:.4f}"
              + (f"   95% CI [{m-1.96*se:+.4f}, {m+1.96*se:+.4f}]" if nm=="lag" else ""))
    m,se,_,res=fit(t,lag)
    rs=sorted(res); n=len(rs)
    print(f"  lag start {lag[0]:.0f} end {lag[-1]:.0f} min {min(lag):.0f} max {max(lag):.0f}")
    print(f"  detrended residual sd {(sum(x*x for x in res)/n)**.5:.1f} blocks "
          f"(p5 {rs[int(n*.05)]:+.1f}, p95 {rs[int(n*.95)]:+.1f})")
    print(f"  endpoint estimate {(lag[-1]-lag[0])/(t[-1]-t[0]):+.4f} blk/min")
    print(f"  baseline 0.1541 within 95% CI: "
          f"{'YES' if m-1.96*se <= 0.1541 <= m+1.96*se else 'NO'}")
