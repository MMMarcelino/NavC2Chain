#!/usr/bin/env python3
"""
Generate the four figures for Sections 6.5 and 6.6 from campaign_unitloss_6.

Inputs (produced by the extraction commands):
    /tmp/c6.log             tracer snapshot
    /tmp/prom6/*.csv        Prometheus range extracts (epoch,node,value)
    /tmp/rounds_c6.log      Besu round-change lines from validator1

Output:
    <OUT>/fig_unitloss_interval.pdf
    <OUT>/fig_unitloss_timeline.pdf
    <OUT>/fig_reconstitution_rounds.pdf
    <OUT>/fig_reconstitution_divergence.pdf

Usage:  python3 make_figures.py [output_dir]
"""
import csv, os, re, sys
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/thesis/chapters/ch6/assets")
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "font.size": 9, "axes.labelsize": 9, "axes.titlesize": 9,
    "legend.fontsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "figure.dpi": 150, "savefig.bbox": "tight", "axes.grid": True,
    "grid.alpha": 0.3, "grid.linewidth": 0.5, "axes.axisbelow": True,
})

# --- ADJUST IF THE MAPPING IS WRONG -----------------------------------------
# validator1 is the log's local node; validator5 is Italy (address from
# add_validator.sh output). The two rejoining nodes are validator3 (FR) and
# validator4 (UK); if the assignment below is reversed, swap the two labels.
ADDR = {
    "6d01aa600fc53332fa92b47710792d46d606448b": "validator1",
    "711877b0aed1992f2ed96fa36f83d0776e1a7a2a": "validator2",
    "c07e4dff25ae4a46249c34b99c7a400697b9cdf1": "validator5",
    "86da488affc9eb93a71b57a6a0b1ecddca21d67f": "validator3",
    "8a218a13db84d75a84bed3c0527ef36c5fb3094f": "validator4",
}
REJOINING = {"validator3", "validator4"}
# ----------------------------------------------------------------------------

T = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
    tzinfo=timezone.utc)


def read_trace(path="/tmp/c6.log"):
    rows, marks = [], []
    for ln in open(path):
        ln = ln.strip()
        if ln.startswith("==="):
            m = re.match(r"=== (.+?) (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)$", ln)
            if m:
                marks.append((T(m.group(2)), m.group(1)))
        elif ln and ln[0].isdigit():
            p = ln.split()
            h = dict(kv.split("=") for kv in p[1].split(","))
            rows.append((T(p[0]), {k: int(v) for k, v in h.items()},
                         int(p[2]), int(p[3])))
    return rows, marks


def read_rounds(path="/tmp/rounds_c6.log"):
    """Returns {node: [(time, round)]} plus [(time, round, expiry_s)]."""
    series, timers = {}, []
    pat = re.compile(
        r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.(\d+)\+0000.*?"
        r"Address: 0x([0-9a-f]+)\s+Round: (\d+)")
    tim = re.compile(
        r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+\+0000.*?"
        r"Moved to round (\d+) which will expire in (\d+) seconds")
    for ln in open(path):
        m = pat.match(ln)
        if m:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc)
            node = ADDR.get(m.group(3), m.group(3)[:6])
            series.setdefault(node, []).append((t, int(m.group(4))))
            continue
        m = tim.match(ln)
        if m:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc)
            timers.append((t, int(m.group(2)), int(m.group(3))))
    return series, timers


def read_prom(name):
    d = {}
    p = "/tmp/prom6/" + name
    if not os.path.exists(p):
        return d
    for ts, node, val in csv.reader(open(p)):
        d.setdefault(node, []).append(
            (datetime.fromtimestamp(float(ts), timezone.utc), float(val)))
    return d


def fmt_time(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=timezone.utc))
    ax.set_xlabel("Time (UTC)")


# ---------------------------------------------------------------- figure 1 ---
def fig_interval():
    labels = ["Full strength\n(four)", "One absent\nof four",
              "Full strength\n(five)", "One absent\nof five"]
    c6 = [2.00, 3.31, 2.01, 3.01]
    c4 = [2.00, 3.33, 1.99, 3.02]
    x = range(len(labels))
    w = 0.36
    fig, ax = plt.subplots(figsize=(6.0, 3.0))
    b1 = ax.bar([i - w / 2 for i in x], c6, w, label="This campaign",
                color="#33628d", edgecolor="black", linewidth=0.4)
    b2 = ax.bar([i + w / 2 for i in x], c4, w, label="Earlier execution",
                color="#b8c9d9", edgecolor="black", linewidth=0.4)
    for b in list(b1) + list(b2):
        ax.annotate(f"{b.get_height():.2f}",
                    (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=7)
    ax.axhline(2.00, ls=":", lw=0.8, color="grey")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("L1 block interval (s)")
    ax.set_ylim(0, 4.0)
    ax.legend(frameon=False, loc="upper left")
    fig.savefig(f"{OUT}/fig_unitloss_interval.pdf")
    plt.close(fig)
    print("wrote fig_unitloss_interval.pdf")


# ---------------------------------------------------------------- figure 2 ---
def fig_timeline():
    rows, marks = read_trace()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 5.0), sharex=True,
                                 height_ratios=[2, 1.4])
    nodes = sorted({k for _, h, _, _ in rows for k in h})
    for n in nodes:
        pts = [(t, h[n]) for t, h, _, _ in rows if n in h]
        a1.plot([p[0] for p in pts], [p[1] for p in pts], lw=0.9, label=n)
    a1.set_ylabel("L1 height")
    a1.legend(frameon=False, ncol=5, fontsize=7, loc="upper left")

    a2.plot([r[0] for r in rows], [r[2] for r in rows], lw=1.1,
            color="#33628d", label="L2 produced")
    a2.plot([r[0] for r in rows], [r[3] for r in rows], lw=1.1,
            color="#c1663a", label="L2 settled")
    a2.set_ylabel("L2 blocks")
    a2.legend(frameon=False, loc="upper left")

    bands = [("P1 FR DOWN", "P1 END", "one absent (3 of 4)"),
             ("P2b FR DOWN", "P2b END", "one absent (4 of 5)"),
             ("P3 HALT", "P3 RESTORE", "below quorum"),
             ("P3b HALT", "P3b RESTORE", "below quorum")]
    for start, end, lab in bands:
        s = next((t for t, n in marks if n.startswith(start)), None)
        e = next((t for t, n in marks if n.startswith(end)), None)
        if s and e:
            for ax in (a1, a2):
                ax.axvspan(s, e, color="grey", alpha=0.16, lw=0)
            a1.annotate(lab, (s, a1.get_ylim()[1]), fontsize=6,
                        rotation=90, va="top", ha="right")
    fmt_time(a2)
    fig.savefig(f"{OUT}/fig_unitloss_timeline.pdf")
    plt.close(fig)
    print("wrote fig_unitloss_timeline.pdf")


# ---------------------------------------------------------------- figure 3 ---
def fig_rounds():
    series, timers = read_rounds()
    if not series:
        print("!! no round data parsed -- check /tmp/rounds_c6.log format")
        return
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    for node in sorted(series):
        pts = sorted(series[node])
        style = dict(lw=1.6, ls="-") if node not in REJOINING else \
            dict(lw=1.3, ls="--")
        ax.step([p[0] for p in pts], [p[1] for p in pts], where="post",
                label=node + (" (rejoining)" if node in REJOINING else ""),
                **style)
    # commit instant: last sample, where the fourth node reaches the top round
    allpts = sorted(p for v in series.values() for p in v)
    if allpts:
        ax.axvline(allpts[-1][0], color="black", lw=0.9, ls=":")
        ax.annotate("quorum reached;\nchain resumes", (allpts[-1][0],
                    0.5), fontsize=7, ha="right", va="bottom",
                    rotation=0, xytext=(-6, 0), textcoords="offset points")
    for t, r, exp in timers:
        ax.annotate(f"r{r}: {exp}s", (t, r), fontsize=6, color="grey",
                    xytext=(3, 3), textcoords="offset points")
    ax.set_ylabel("QBFT round")
    ax.set_yticks(range(0, 9))
    ax.legend(frameon=False, fontsize=7, loc="upper left", ncol=2)
    fmt_time(ax)
    fig.savefig(f"{OUT}/fig_reconstitution_rounds.pdf")
    plt.close(fig)
    print("wrote fig_reconstitution_rounds.pdf")


# ---------------------------------------------------------------- figure 4 ---
def fig_divergence():
    rows, marks = read_trace()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 4.4), sharex=True,
                                 height_ratios=[2, 1])
    t = [r[0] for r in rows]
    a1.plot(t, [r[2] for r in rows], lw=1.2, color="#33628d",
            label="L2 produced")
    a1.plot(t, [r[3] for r in rows], lw=1.2, color="#c1663a",
            label="L2 settled")
    a1.set_ylabel("L2 blocks")
    a1.legend(frameon=False, loc="upper left")

    a2.plot(t, [r[2] - r[3] for r in rows], lw=1.2, color="black")
    a2.set_ylabel("Lag (blocks)")

    for start, end in (("P3 HALT", "P3 RESTORE"), ("P3b HALT", "P3b RESTORE")):
        s = next((x for x, n in marks if n.startswith(start)), None)
        e = next((x for x, n in marks if n.startswith(end)), None)
        if s and e:
            for ax in (a1, a2):
                ax.axvspan(s, e, color="grey", alpha=0.18, lw=0)
    # manual repairs
    for lab, when in (("repair 1", "2026-08-19T10:44:30Z"),
                      ("repair 2", "2026-08-19T11:07:28Z")):
        w = T(when)
        if t and t[0] <= w <= t[-1]:
            for ax in (a1, a2):
                ax.axvline(w, color="#7a3b8f", lw=0.9, ls="-.")
            a2.annotate(lab, (w, a2.get_ylim()[1]), fontsize=6, rotation=90,
                        ha="right", va="top")
    fmt_time(a2)
    fig.savefig(f"{OUT}/fig_reconstitution_divergence.pdf")
    plt.close(fig)
    print("wrote fig_reconstitution_divergence.pdf")


if __name__ == "__main__":
    fig_interval()
    fig_timeline()
    fig_rounds()
    fig_divergence()
    print("output directory:", OUT)
