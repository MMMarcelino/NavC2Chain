import os, re
from datetime import datetime, timezone
pat=re.compile(r'^(\d{4}-\d\d-\d\dT[\d:]+Z)\s+(\d+)\s+(\d+)\s+(-?\d+)\s*$')
for r in ("r3","r4"):
    rows=[]
    for line in open(os.path.expanduser(f"~/AppChain/patrol_{r}_trace.log"), errors="replace"):
        m=pat.match(line.strip())
        if m:
            ts=datetime.strptime(m.group(1),"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            rows.append((ts, int(m.group(2)), int(m.group(3))))
    rows.sort()
    print(f"\n=== patrol-{r}   time      gap  blocks  lag")
    last=None; cum=0
    for ts,p,s in rows:
        if last is None: last=(ts,s); continue
        if s>last[1]:
            gap=(ts-last[0]).total_seconds(); size=s-last[1]; cum+=size
            flag=""
            if gap>150: flag=" <-- STALL"
            elif size!=12: flag=" <-- off-modal"
            print(f"  {ts.strftime('%H:%M:%S')}  {gap:5.0f}  {size:5d}  {p-s:5d}{flag}")
            last=(ts,s)
    print(f"  total {cum} blocks settled")
