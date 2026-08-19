#!/usr/bin/env python3
"""
Figures for Chapter 6, Section 6.4 (Capacity margin).
Campaign of 2026-08-18, rate ladder 6 -> 10 tx/s.

Run from ~/AppChain/driver (where prom_*.json and runs/ live):

    python3 make_capmargin_figs.py

Writes three PDFs into ASSETS (edit the path if your tree differs):
    fig_capmargin_throughput.pdf
    fig_capmargin_proving.pdf
    fig_capmargin_timeline.pdf
"""

import json
import glob
import os
import re
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ----------------------------------------------------------------------
# configuration
# ----------------------------------------------------------------------

ASSETS = os.path.expanduser("~/thesis/chapters/ch6/assets")   # <-- adjust
RUNS = "runs"
CAMPAIGN_DATE = "2026-08-18"

plt.rcParams.update({
    "font.size": 7,
    "axes.labelsize": 7,
    "axes.titlesize": 8,
    "xtick.labelsize": 6,
    "ytick.labelsize": 6,
    "legend.fontsize": 6,
    "lines.linewidth": 1.0,
    "lines.markersize": 3.0,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.4,
})

C_MEDIAN = "#B03A2E"
C_P90 = "#C0392B"
C_MAIN = "#1F6F54"
C_ALT = "#2E86C1"
C_GAP = "#CCCCCC"


# ----------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------

def load_steps():
    """Return the ladder steps, ordered by target rate.

    Start time comes from the filename, duration from the summary itself,
    so the step windows are derived from the run record rather than typed
    in by hand.
    """
    steps = []
    pattern = os.path.join(RUNS, f"capmargin-*tps-{CAMPAIGN_DATE}T*.summary.json")
    for path in sorted(glob.glob(pattern)):
        with open(path) as fh:
            s = json.load(fh)
        m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-(\d{3})Z", path)
        stamp = m.group(1)
        t0 = datetime.strptime(stamp, "%Y-%m-%dT%H-%M-%S").replace(tzinfo=timezone.utc)
        start = t0.timestamp() + int(m.group(2)) / 1000.0
        steps.append({
            "rate": s["target_rate_tps"],
            "start": start,
            "end": start + s["elapsed_s"],
            "elapsed": s["elapsed_s"],
            "submitted": s["submitted"],
            "accepted": s["accepted"],
            "failed": s["failed"],
            "achieved": s["achieved_tps"],
            "lat": s["latency_ms"],
        })
    steps.sort(key=lambda d: d["rate"])
    if not steps:
        raise SystemExit(f"no summary files matched {pattern}")
    return steps


def load_series(metric):
    """Load one prom_<metric>.json range query as (times, values) arrays."""
    path = f"prom_{metric}.json"
    with open(path) as fh:
        doc = json.load(fh)
    result = doc["data"]["result"]
    if not result:
        raise SystemExit(f"{path}: empty result")
    pairs = result[0]["values"]
    t = np.array([float(p[0]) for p in pairs])
    v = np.array([float(p[1]) for p in pairs])
    return t, v


def completions_in(t, v, start, end):
    """Values of a last-write gauge that were newly written inside a window.

    The gauge holds its previous reading between proofs, so a completed
    proof is a change in value, not a sample.
    """
    out = []
    for i in range(len(t)):
        if not (start <= t[i] <= end):
            continue
        if i == 0 or v[i] != v[i - 1]:
            out.append(v[i])
    return np.array(out)


def counter_delta(t, v, start, end):
    """Increase of a monotonic counter across a window.

    Read from the counter itself rather than from sample density, so a
    scrape gap inside the window does not lose completions.
    """
    before = v[t <= start]
    inside = v[(t >= start) & (t <= end)]
    if len(inside) == 0:
        return 0.0
    lo = before[-1] if len(before) else inside[0]
    return float(inside[-1] - lo)


def find_gaps(t, threshold=60.0):
    """Scrape gaps: intervals where Prometheus recorded nothing."""
    gaps = []
    d = np.diff(t)
    for i, dt in enumerate(d):
        if dt > threshold:
            gaps.append((t[i], t[i + 1]))
    return gaps


# ----------------------------------------------------------------------
# figure 1: throughput and latency against offered load
# ----------------------------------------------------------------------

def fig_throughput(steps):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.3, 2.3))

    rates = [s["rate"] for s in steps]
    achieved = [s["achieved"] for s in steps]

    lim = [min(rates) - 0.5, max(rates) + 0.5]
    ax1.plot(lim, lim, ls=":", color="grey", lw=0.8, label="offered = achieved")
    ax1.plot(rates, achieved, "o-", color=C_MAIN, label="achieved")
    ax1.set_xlabel("Offered load (tx/s)")
    ax1.set_ylabel("Achieved throughput (tx/s)")
    ax1.set_title("Throughput")
    ax1.set_xlim(lim)
    ax1.set_ylim(0, max(rates) + 0.5)
    ax1.legend(loc="upper left")

    p50 = [s["lat"]["p50"] / 1000.0 for s in steps]
    p90 = [s["lat"]["p90"] / 1000.0 for s in steps]
    mean = [s["lat"]["mean"] / 1000.0 for s in steps]
    mx = [s["lat"]["max"] / 1000.0 for s in steps]

    ax2.plot(rates, p50, "o-", color=C_ALT, label="median")
    ax2.plot(rates, mean, "s--", color=C_MAIN, label="mean")
    ax2.plot(rates, mx, "^-.", color=C_P90, label="maximum")
    ax2.set_yscale("log")
    ax2.set_xlabel("Offered load (tx/s)")
    ax2.set_ylabel("Acceptance latency (s)")
    ax2.set_title("Acceptance latency")
    ax2.legend(loc="upper left")

    fig.tight_layout()
    out = os.path.join(ASSETS, "fig_capmargin_throughput.pdf")
    fig.savefig(out)
    plt.close(fig)
    print("wrote", out)


# ----------------------------------------------------------------------
# figure 2: proving response
# ----------------------------------------------------------------------

def fig_proving(steps):
    tg, vg = load_series("proof_generation_seconds")
    tc, vc = load_series("proof_batches_succeeded_total")
    ts, vs = load_series("proof_size_bytes")

    rates, med, lo, hi, rate_per_min, size_mib = [], [], [], [], [], []
    for s in steps:
        g = completions_in(tg, vg, s["start"], s["end"])
        z = completions_in(ts, vs, s["start"], s["end"])
        n = counter_delta(tc, vc, s["start"], s["end"])
        rates.append(s["rate"])
        med.append(np.median(g) if len(g) else np.nan)
        lo.append(g.min() if len(g) else np.nan)
        hi.append(g.max() if len(g) else np.nan)
        rate_per_min.append(n / (s["elapsed"] / 60.0))
        size_mib.append(np.median(z) / 2**20 if len(z) else np.nan)

    med = np.array(med); lo = np.array(lo); hi = np.array(hi)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.3, 2.3))

    ax1.fill_between(rates, lo, hi, color=C_MEDIAN, alpha=0.15, label="min-max")
    ax1.plot(rates, med, "o-", color=C_MEDIAN, label="median")
    ax1.set_xlabel("Offered load (tx/s)")
    ax1.set_ylabel("Proof generation time (s)")
    ax1.set_title("Proof generation time")
    ax1.legend(loc="upper left")

    ax2.plot(rates, rate_per_min, "o-", color=C_MAIN, label="batches completed")
    ax2.set_xlabel("Offered load (tx/s)")
    ax2.set_ylabel("Completed batches (min$^{-1}$)")
    ax2.set_title("Batch completion rate")
    ax2.set_ylim(0, max(rate_per_min) * 1.25)

    ax2b = ax2.twinx()
    ax2b.plot(rates, size_mib, "s--", color=C_ALT, label="proof size")
    ax2b.set_ylabel("Median proof size (MiB)")
    ax2b.set_ylim(0, 25)
    ax2b.grid(False)

    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax2b.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, loc="lower left")

    fig.tight_layout()
    out = os.path.join(ASSETS, "fig_capmargin_proving.pdf")
    fig.savefig(out)
    plt.close(fig)
    print("wrote", out)

    # console table, for pasting the numbers into the .tex
    print("\n  offered  batches  per-min   median    min      max    size MiB")
    for i, r in enumerate(rates):
        print(f"  {r:5d}   {rate_per_min[i]*steps[i]['elapsed']/60:6.0f}  "
              f"{rate_per_min[i]:7.3f}  {med[i]:7.1f}  {lo[i]:7.1f}  "
              f"{hi[i]:7.1f}  {size_mib[i]:7.2f}")


# ----------------------------------------------------------------------
# figure 3: timeline, queue depth and artefact growth, with blackouts
# ----------------------------------------------------------------------

def fig_timeline(steps):
    tq, vq = load_series("gateway_jobs_in_flight")
    tb, vb = load_series("gateway_storage_total_bytes")
    tp, vp = load_series("madara_block_produced_no")
    tl, vl = load_series("madara_l1_block_number")

    t0 = steps[0]["start"]
    gaps = find_gaps(tq, threshold=60.0)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(6.3, 4.8), sharex=True)

    for ax in (ax1, ax2, ax3):
        for g0, g1 in gaps:
            ax.axvspan((g0 - t0) / 60.0, (g1 - t0) / 60.0,
                       color=C_GAP, alpha=0.7, lw=0, zorder=0)
        for s in steps:
            ax.axvline((s["start"] - t0) / 60.0, color="grey",
                       lw=0.5, ls=":", zorder=1)

    ax1.plot((tq - t0) / 60.0, vq, color=C_MAIN, lw=0.8)
    ax1.set_ylabel("Jobs in flight")
    ax1.set_title("Gateway queue depth and artefact accumulation")

    for s in steps:
        mid = ((s["start"] + s["end"]) / 2 - t0) / 60.0
        ax1.text(mid, ax1.get_ylim()[1] * 0.92, f"{s['rate']}",
                 ha="center", va="top", fontsize=6, color="black")

    ax2.plot((tb - t0) / 60.0, vb / 2**30, color=C_ALT, lw=0.9)
    ax2.set_ylabel("Stored artefacts (GiB)")

    ax3.plot((tp - t0) / 60.0, vp, color=C_MAIN, lw=0.9, label="produced")
    ax3.plot((tl - t0) / 60.0, vl, color=C_MEDIAN, lw=0.9, label="settled")
    ax3.set_ylabel("L2 block height")
    ax3.set_xlabel(f"Elapsed time (min from {CAMPAIGN_DATE} 16:08 UTC)")
    ax3.legend(loc="upper left")

    if gaps:
        ax1.text(0.99, 0.05, "shaded: no metrics scraped",
                 transform=ax1.transAxes, ha="right", va="bottom",
                 fontsize=6, color="dimgrey")

    fig.tight_layout()
    out = os.path.join(ASSETS, "fig_capmargin_timeline.pdf")
    fig.savefig(out)
    plt.close(fig)
    print("wrote", out)

    for g0, g1 in gaps:
        a = datetime.fromtimestamp(g0, timezone.utc).strftime("%H:%M:%S")
        b = datetime.fromtimestamp(g1, timezone.utc).strftime("%H:%M:%S")
        print(f"  scrape gap {a}Z -> {b}Z  ({g1 - g0:.0f} s)")


# ----------------------------------------------------------------------

def main():
    os.makedirs(ASSETS, exist_ok=True)
    steps = load_steps()

    print("steps:")
    for s in steps:
        a = datetime.fromtimestamp(s["start"], timezone.utc).strftime("%H:%M:%S")
        b = datetime.fromtimestamp(s["end"], timezone.utc).strftime("%H:%M:%S")
        print(f"  {s['rate']:2d} tx/s  {a}Z -> {b}Z  {s['elapsed']:7.1f} s  "
              f"achieved {s['achieved']:.3f}  accepted {s['accepted']}  "
              f"failed {s['failed']}")
    total = sum(s["accepted"] for s in steps)
    print(f"  total accepted across ladder: {total}")

    fig_throughput(steps)
    fig_proving(steps)
    fig_timeline(steps)


if __name__ == "__main__":
    main()
