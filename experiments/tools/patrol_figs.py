import csv, os, re, json
from datetime import datetime, timezone
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

HOME = os.path.expanduser("~")
RUNS = f"{HOME}/AppChain/experiments/driver/runs"
BASE = f"{HOME}/AppChain/experiments/baseline"
OUT  = f"{HOME}/AppChain/experiments/figures"
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.family":"serif","font.size":9,"axes.linewidth":0.6,
                     "grid.linewidth":0.3,"legend.frameon":False,
                     "xtick.direction":"in","ytick.direction":"in"})
C = {"E1":"#4C4C4C","r2":"#1f77b4","r3":"#d62728","r4":"#2ca02c"}

def jsonl(pat):
    import glob
    f = sorted(glob.glob(f"{RUNS}/{pat}"))[0]
    return [json.loads(l) for l in open(f) if l.strip()]

def ecdf(v):
    v = np.sort(np.asarray(v, float))
    return v, np.arange(1, len(v)+1)/len(v)

# ---------- 1. latency ------------------------------------------------
src = {"E1":"E1-routine-patrol-*.jsonl","r2":"patrol-r2-*.jsonl",
       "r3":"patrol-r3-*.jsonl","r4":"patrol-r4-*.jsonl"}
fig, ax = plt.subplots(1, 2, figsize=(6.4,2.9))
for k, pat in src.items():
    d = jsonl(pat)
    x, y = ecdf([r["accept_ms"] for r in d])
    ax[0].plot(x, y, lw=1.0, color=C[k], label=k)
    x, y = ecdf([r["accept_ms"]-r["submit_ms"] for r in d])
    ax[1].plot(x, y, lw=1.0, color=C[k], label=k)
ax[0].set_xlabel("end-to-end acceptance (ms)"); ax[0].set_xlim(1995, 2110)
ax[1].set_xlabel("chain-side acceptance (ms)"); ax[1].set_xlim(1995, 2035)
ax[0].set_ylabel("cumulative fraction"); ax[0].legend(loc="lower right", fontsize=8)
for a in ax: a.grid(alpha=.35); a.set_ylim(0,1.02)
fig.tight_layout(); fig.savefig(f"{OUT}/fig_patrol_latency.pdf"); plt.close(fig)

# ---------- shared: settlement steps ----------------------------------
def steps_from(rows):
    """rows: sorted (epoch_seconds, settled). returns [(gap_s, blocks, t_end)]"""
    out=[]; last=None
    for ts,s in rows:
        if last is None: last=(ts,s); continue
        if s>last[1]: out.append((ts-last[0], s-last[1], ts)); last=(ts,s)
    return out

pat = re.compile(r'^(\d{4}-\d\d-\d\dT[\d:]+Z)\s+(\d+)\s+(\d+)\s+(-?\d+)\s*$')
def trace(r):
    rows=[]
    for line in open(f"{HOME}/AppChain/patrol_{r}_trace.log", errors="replace"):
        m = pat.match(line.strip())
        if m:
            t = datetime.strptime(m.group(1),"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            rows.append((t.timestamp(), int(m.group(2)), int(m.group(3))))
    rows.sort(); return rows

def basecsv(name):
    with open(f"{BASE}/{name}") as f:
        return sorted((float(r["timestamp"]), float(r["value"])) for r in csv.DictReader(f))

# ---------- 2. settlement quantisation --------------------------------
bsteps = steps_from(basecsv("blocks_settled.csv"))
tr = {r: trace(r) for r in ("r3","r4")}
lsteps = []
for r in ("r3","r4"):
    lsteps += steps_from([(t,s) for t,_,s in tr[r]])

fig = plt.figure(figsize=(6.4,4.4))
gs = fig.add_gridspec(2, 2, height_ratios=[1,1.15], hspace=.42, wspace=.28)

a = fig.add_subplot(gs[0,0])
for lab, st, col in (("idle, 15 h", bsteps, "#4C4C4C"), ("0.4 tx/s", lsteps, "#d62728")):
    sz = [b for _,b,_ in st]
    ed = np.arange(5.5, 21.5, 1)
    a.hist(sz, bins=ed, density=True, histtype="step", lw=1.1, color=col, label=lab)
a.axvline(12, color="k", lw=.6, ls=":")
a.set_xlabel("L2 blocks per settlement"); a.set_ylabel("fraction"); a.legend(fontsize=8)
a.grid(alpha=.35)

a = fig.add_subplot(gs[0,1])
for lab, st, col in (("idle, 15 h", bsteps, "#4C4C4C"), ("0.4 tx/s", lsteps, "#d62728")):
    g = np.array([x[0] for x in st])
    a.hist(g, bins=np.arange(75,255,30), density=True, histtype="step", lw=1.1,
           color=col, label=lab)
a.axvline(120, color="k", lw=.6, ls=":")
a.set_xlabel("settlement interval (s)"); a.set_ylabel("fraction"); a.grid(alpha=.35)

a = fig.add_subplot(gs[1,:])
for r in ("r3","r4"):
    t0 = tr[r][0][0]
    tm = [(x[0]-t0)/60 for x in tr[r]]
    lag = [x[1]-x[2] for x in tr[r]]
    off = 0 if r=="r3" else (tr["r4"][0][0]-tr["r3"][0][0])/60
    a.plot([x+off for x in tm], lag, lw=.9, color=C[r], label=f"patrol-{r}")
    for g,b,te in steps_from([(t,s) for t,_,s in tr[r]]):
        if g > 150:
            a.plot((te-tr["r3"][0][0])/60, np.interp(te, [x[0] for x in tr[r]],
                   [x[1]-x[2] for x in tr[r]]), marker="v", ms=4.5,
                   color=C[r], mec="k", mew=.4, zorder=5)
a.set_xlabel("minutes from start of patrol-r3"); a.set_ylabel("settlement lag (L2 blocks)")
a.legend(fontsize=8, loc="upper right"); a.grid(alpha=.35)
a.annotate("stall", xy=(0.015,0.08), xycoords="axes fraction", fontsize=7.5)
a.plot(0.008, 0.115, marker="v", ms=4.5, color="0.4", mec="k", mew=.4,
       transform=a.transAxes, clip_on=False)
fig.savefig(f"{OUT}/fig_patrol_settlement.pdf", bbox_inches="tight"); plt.close(fig)

# ---------- 3. stall mechanism ----------------------------------------
stalls = [(t, g, b) for g,b,t in bsteps if g > 150]
gaps = np.diff([s[0] for s in stalls])/60
lost = [int(round(g/10 - b)) for _,g,b in stalls]

fig, ax = plt.subplots(1, 2, figsize=(6.4,2.7))
m = gaps.mean()
ax[0].hist(gaps, bins=np.arange(0, 190, 15), density=True, histtype="stepfilled",
           color="#bdd7e7", ec="#1f77b4", lw=1.0)
x = np.linspace(0, 180, 200)
ax[0].plot(x, np.exp(-x/m)/m, "k--", lw=1.0,
           label=f"exponential, mean {m:.0f} min")
ax[0].set_xlabel("interval between stalls (min)"); ax[0].set_ylabel("density")
ax[0].legend(fontsize=7.5); ax[0].grid(alpha=.35)

ed = np.arange(2.5, 21.5, 1)
ax[1].hist(lost, bins=ed, histtype="stepfilled", color="#fcbba1", ec="#d62728", lw=1.0)
ax[1].set_xlabel("L2 blocks lost per stall"); ax[1].set_ylabel("count")
ax[1].grid(alpha=.35)
fig.tight_layout(); fig.savefig(f"{OUT}/fig_patrol_stalls.pdf"); plt.close(fig)

print(f"CV {gaps.std(ddof=1)/m:.2f}, {len(stalls)} stalls, "
      f"mean loss {np.mean(lost):.1f} blocks, total {sum(lost)} blocks")
print("written:", ", ".join(sorted(os.listdir(OUT))))
