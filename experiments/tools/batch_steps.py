import os, re
from datetime import datetime, timezone
pat=re.compile(r'^(\d{4}-\d\d-\d\dT[\d:]+Z)\s+(\d+)\s+(\d+)\s+(-?\d+)\s*$')
for r in ("r3","r4"):
    rows=[]
    for line in open(os.path.expanduser(f"~/AppChain/patrol_{r}_trace.log"), errors="replace"):
        m=pat.match(line.strip())
        if m:
            ts=datetime.strptime(m.group(1),"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            rows.append((ts.timestamp(), int(m.group(2)), int(m.group(3))))
    rows.sort()
    steps=[]; last=None
    for ts,_,s in rows:
        if last is None: last=(ts,s); continue
        if s>last[1]:
            steps.append((ts-last[0], s-last[1])); last=(ts,s)
    sz=[x[1] for x in steps]; iv=[x[0] for x in steps]
    print(f"\n=== patrol-{r}: {len(steps)} settlement events")
    print(f"  blocks/batch  mean {sum(sz)/len(sz):.2f}  min {min(sz)}  max {max(sz)}")
    print(f"  interval s    mean {sum(iv)/len(iv):.1f}  min {min(iv):.0f}  max {max(iv):.0f}")
    hist={}
    for v in sz: hist[v]=hist.get(v,0)+1
    print("  distribution: " + "  ".join(f"{k}:{v}" for k,v in sorted(hist.items())))
    print(f"  implied settled rate {sum(sz)/(sum(iv)/60):.3f} blk/min")
