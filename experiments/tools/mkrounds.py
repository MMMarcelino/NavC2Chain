import re, sys, os
from datetime import datetime, timezone
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates

OUT = sys.argv[1] if len(sys.argv)>1 else os.path.expanduser("~/thesis/chapters/ch6/assets")
plt.rcParams.update({"font.size":9,"legend.fontsize":7,"xtick.labelsize":8,
    "ytick.labelsize":8,"axes.labelsize":9,"figure.dpi":150,
    "savefig.bbox":"tight","axes.grid":True,"grid.alpha":.3,"axes.axisbelow":True})

ADDR = {"6d01aa600fc53332fa92b47710792d46d606448b":"validator1",
        "711877b0aed1992f2ed96fa36f83d0776e1a7a2a":"validator2",
        "c07e4dff25ae4a46249c34b99c7a400697b9cdf1":"validator5 (Italy)",
        "86da488affc9eb93a71b57a6a0b1ecddca21d67f":"validator3 (FR)",
        "8a218a13db84d75a84bed3c0527ef36c5fb3094f":"validator4 (UK)"}
REJOIN = {"validator3 (FR)","validator4 (UK)"}

PA = re.compile(r"Address: 0x([0-9a-f]+)\s+Round: (\d+)")
PT = re.compile(r"Moved to round (\d+) which will expire in (\d+) seconds")
TS = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")

series, timers = {}, []
for ln in open("/tmp/rounds_c6.log"):
    mt = TS.search(ln)
    if not mt: continue
    t = datetime.strptime(mt.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    m = PA.search(ln)
    if m:
        series.setdefault(ADDR.get(m.group(1), m.group(1)[:6]), []).append((t,int(m.group(2))))
        continue
    m = PT.search(ln)
    if m: timers.append((t,int(m.group(1)),int(m.group(2))))

print("nodes:", {k:len(v) for k,v in series.items()}, "timers:", len(timers))

W = [("First reconstitution","10:33:30","10:41:30"),
     ("Second reconstitution","10:49:20","11:05:30")]
D = "2026-08-19T%sZ"
fig, axes = plt.subplots(1,2,figsize=(7.0,3.2),sharey=True)
for ax,(title,a,b) in zip(axes,W):
    t0 = datetime.strptime(D%a,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    t1 = datetime.strptime(D%b,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    last = None
    for node in sorted(series):
        p = [x for x in sorted(series[node]) if t0<=x[0]<=t1]
        if not p: continue
        st = dict(lw=1.3,ls="--") if node in REJOIN else dict(lw=1.7,ls="-")
        ax.step([x[0] for x in p],[x[1] for x in p],where="post",label=node,**st)
        if node in REJOIN: last = p[-1][0] if last is None else max(last,p[-1][0])
    for t,r,e in timers:
        if t0<=t<=t1: ax.annotate(f"{e}s",(t,r),fontsize=6,color="grey",
                                  xytext=(2,2),textcoords="offset points")
    if last:
        ax.axvline(last,color="black",lw=.9,ls=":")
        ax.annotate("quorum",(last,0.2),fontsize=6,ha="right",
                    xytext=(-3,0),textcoords="offset points")
    ax.set_title(title,fontsize=9); ax.set_xlim(t0,t1)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M",tz=timezone.utc))
    ax.set_xlabel("Time (UTC)")
axes[0].set_ylabel("QBFT round"); axes[0].set_yticks(range(0,9))
axes[0].legend(frameon=False,loc="upper left",ncol=1)
fig.savefig(f"{OUT}/fig_reconstitution_rounds.pdf")
print("wrote fig_reconstitution_rounds.pdf ->", OUT)
