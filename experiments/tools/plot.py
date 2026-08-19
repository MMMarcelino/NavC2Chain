#!/usr/bin/env python3
"""Turn the extracted CSVs into vector figures for the dissertation.

    pip install matplotlib --break-system-packages
    ./plot.py --in baseline --out figures

Produces PDFs sized for \\includegraphics[width=\\textwidth]{...} in a 12pt
document, with serif type so they sit alongside the body text rather than
looking like screenshots. Every figure is drawn from a CSV, so it can be
regenerated after the chain is gone.
"""

import argparse
import csv
import json
import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

AP = argparse.ArgumentParser()
AP.add_argument('--in', dest='indir', default='baseline')
AP.add_argument('--out', dest='outdir', default='figures')
AP.add_argument('--format', default='pdf', choices=['pdf', 'png', 'svg'])
ARGS = AP.parse_args()

os.makedirs(ARGS.outdir, exist_ok=True)

plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 9,
    'axes.labelsize': 9,
    'axes.titlesize': 10,
    'legend.fontsize': 8,
    'xtick.labelsize': 8,
    'ytick.labelsize': 8,
    'axes.grid': True,
    'grid.alpha': 0.25,
    'grid.linewidth': 0.5,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'figure.dpi': 150,
    'savefig.bbox': 'tight',
    'savefig.pad_inches': 0.02,
})

W = 6.3          # \textwidth in inches for a typical A4 12pt thesis
PALETTE = ['#2F6EA5', '#C1554E', '#4E8F5B', '#8A6BB1', '#B4863C', '#5C5C5C']


def load(name):
    path = os.path.join(ARGS.indir, f'{name}.csv')
    if not os.path.exists(path):
        return None, None
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None, None
    cols = [c for c in rows[0] if c not in ('timestamp', 'iso')]
    t0 = int(rows[0]['timestamp'])
    hours = [(int(r['timestamp']) - t0) / 3600 for r in rows]
    data = {}
    for c in cols:
        data[c] = [float(r[c]) if r[c] not in ('', None) else None for r in rows]
    return hours, data


def save(fig, name):
    p = os.path.join(ARGS.outdir, f'{name}.{ARGS.format}')
    fig.savefig(p)
    plt.close(fig)
    print(f'  {p}')


def clean(xs, ys):
    return zip(*[(x, y) for x, y in zip(xs, ys) if y is not None]) or ((), ())


SUMMARY = {}
sp = os.path.join(ARGS.indir, 'summary.json')
if os.path.exists(sp):
    SUMMARY = json.load(open(sp))

print(f'writing {ARGS.format} figures to {ARGS.outdir}/')

# ------------------------------------------------------- 1. proof timing ----
h, d = load('proof_time')
if h:
    fig, ax = plt.subplots(figsize=(W, 2.6))
    x, y = clean(h, d['value'])
    ax.plot(x, y, '.', ms=2.0, color=PALETTE[0], alpha=0.55,
            label='individual proof')
    for series, colour, style, lbl in (
            ('proof_time_p50', PALETTE[1], '-', 'p50'),
            ('proof_time_p90', PALETTE[2], '--', 'p90')):
        hh, dd = load(series)
        if hh:
            xx, yy = clean(hh, dd['value'])
            ax.plot(xx, yy, style, lw=1.2, color=colour, label=lbl)
    ax.set_xlabel('elapsed time (h)')
    ax.set_ylabel('proof generation time (s)')
    ax.set_ylim(bottom=0)
    ax.legend(loc='upper right', ncol=3, frameon=False)
    save(fig, 'proof_generation_time')

# --------------------------------------------- 2. proof time distribution ---
hp = os.path.join(ARGS.indir, 'proof_time_histogram.csv')
if os.path.exists(hp):
    rows = [r for r in csv.DictReader(open(hp))]
    edges, counts, cum = [], [], []
    for r in rows:
        if r['le_seconds'] == 'inf':
            continue
        edges.append(float(r['le_seconds']))
        counts.append(float(r['bucket_count']))
        cum.append(float(r['cumulative_count']))
    if edges and sum(counts) > 0:
        fig, ax = plt.subplots(figsize=(W, 2.4))
        widths = [edges[0]] + [edges[i] - edges[i - 1] for i in range(1, len(edges))]
        ax.bar([e - w / 2 for e, w in zip(edges, widths)], counts, width=widths,
               color=PALETTE[0], alpha=0.75, edgecolor='white', linewidth=0.4)
        ax.set_xlabel('proof generation time (s)')
        ax.set_ylabel('number of proofs')
        total = cum[-1] if cum else 0
        if total:
            ax2 = ax.twinx()
            ax2.plot(edges, [c / total * 100 for c in cum], color=PALETTE[1], lw=1.2)
            ax2.set_ylabel('cumulative (%)')
            ax2.set_ylim(0, 105)
            ax2.grid(False)
        lo = min(e for e, c in zip(edges, counts) if c > 0)
        hi = max(e for e, c in zip(edges, counts) if c > 0)
        ax.set_xlim(max(0, lo - 5), hi + 5)
        save(fig, 'proof_time_distribution')

# ------------------------------------------------------- 3. proof size -----
h, d = load('proof_size')
if h:
    fig, ax = plt.subplots(figsize=(W, 2.3))
    x, y = clean(h, d['value'])
    ax.plot(x, [v / 2**20 for v in y], '.', ms=2.0, color=PALETTE[0], alpha=0.6)
    ax.set_xlabel('elapsed time (h)')
    ax.set_ylabel('proof size (MiB)')
    ax.set_ylim(bottom=0)
    save(fig, 'proof_size')

# ------------------------------------------- 4. production vs settlement ---
hp_, dp = load('blocks_produced')
hs_, ds = load('blocks_settled')
hl, dl = load('settlement_lag')
if hp_ and hs_:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(W, 4.0), sharex=True,
                                   gridspec_kw={'height_ratios': [2, 1]})
    x, y = clean(hp_, dp['value']); ax1.plot(x, y, lw=1.4, color=PALETTE[0],
                                             label='blocks produced (L2)')
    x, y = clean(hs_, ds['value']); ax1.plot(x, y, lw=1.4, color=PALETTE[1],
                                             label='blocks settled (anchored on L1)')
    ax1.set_ylabel('cumulative blocks')
    ax1.legend(loc='upper left', frameon=False)
    if hl:
        x, y = clean(hl, dl['value'])
        ax2.fill_between(x, y, color=PALETTE[2], alpha=0.30)
        ax2.plot(x, y, lw=1.0, color=PALETTE[2])
    ax2.set_ylabel('lag (blocks)')
    ax2.set_xlabel('elapsed time (h)')
    ax2.set_ylim(bottom=0)
    save(fig, 'production_vs_settlement')

# ------------------------------------------------- 5. ledger consistency ---
h, d = load('validator_height')
hs2, dsp = load('height_spread')
if h:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(W, 3.8), sharex=True,
                                   gridspec_kw={'height_ratios': [2, 1]})
    for i, (node, ys) in enumerate(sorted(d.items())):
        x, y = clean(h, ys)
        ax1.plot(x, y, lw=1.1, color=PALETTE[i % len(PALETTE)], label=node,
                 alpha=0.9)
    ax1.set_ylabel('chain head (block)')
    ax1.legend(loc='upper left', ncol=4, frameon=False)
    if hs2:
        x, y = clean(hs2, dsp['value'])
        ax2.plot(x, y, lw=0.9, color=PALETTE[5])
        ax2.set_ylim(-0.2, max(3.2, (max(y) if y else 1) + 0.5))
    ax2.set_ylabel('spread\n(blocks)')
    ax2.set_xlabel('elapsed time (h)')
    save(fig, 'ledger_consistency')

# ---------------------------------------------------- 6. platform cost -----
hc, dc = load('validator_cpu')
hm, dm = load('validator_rss')
if hc or hm:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(W, 2.4))
    if hc:
        for i, (node, ys) in enumerate(sorted(dc.items())):
            x, y = clean(hc, ys)
            ax1.plot(x, y, lw=0.9, color=PALETTE[i % len(PALETTE)], label=node)
        ax1.set_ylabel('CPU (cores)')
        ax1.set_xlabel('elapsed time (h)')
        ax1.set_ylim(bottom=0)
        ax1.legend(frameon=False, ncol=2)
    if hm:
        for i, (node, ys) in enumerate(sorted(dm.items())):
            x, y = clean(hm, ys)
            ax2.plot(x, [v / 2**20 for v in y], lw=0.9,
                     color=PALETTE[i % len(PALETTE)], label=node)
        ax2.set_ylabel('resident memory (MiB)')
        ax2.set_xlabel('elapsed time (h)')
        ax2.set_ylim(bottom=0)
    save(fig, 'platform_cost')

# --------------------------------------------------------- 7. storage ------
parts = [('storage_proofs', 'proof JSONs'), ('storage_pies', 'Cairo PIE zips'),
         ('storage_inputs', 'program inputs'), ('storage_logs', 'run logs')]
series = [(lbl, load(n)) for n, lbl in parts]
series = [(lbl, hh, dd) for lbl, (hh, dd) in series if hh]
if series:
    fig, ax = plt.subplots(figsize=(W, 2.6))
    base = None
    for i, (lbl, hh, dd) in enumerate(series):
        y = [(v or 0) / 2**30 for v in dd['value']]
        if base is None:
            base = [0.0] * len(y)
        top = [b + v for b, v in zip(base, y)]
        ax.fill_between(hh, base, top, label=lbl,
                        color=PALETTE[i % len(PALETTE)], alpha=0.75, lw=0)
        base = top
    ax.set_xlabel('elapsed time (h)')
    ax.set_ylabel('cumulative storage (GiB)')
    ax.legend(loc='upper left', frameon=False)
    ax.set_ylim(bottom=0)
    save(fig, 'storage_growth')

# ------------------------------------------------- 8. batch composition ----
hb, db = load('batch_size_pies')
ha, da = load('aggregator_children')
if hb or ha:
    fig, ax = plt.subplots(figsize=(W, 2.3))
    vals = []
    if hb:
        x, y = clean(hb, db['value'])
        ax.step(x, y, where='post', lw=0.9, color=PALETTE[0],
                label='PIEs per proof batch')
        vals += list(y)
    if ha:
        x, y = clean(ha, da['value'])
        ax.step(x, y, where='post', lw=0.9, color=PALETTE[1],
                label='proofs per settlement batch')
        vals += list(y)
    ax.set_xlabel('elapsed time (h)')
    ax.set_ylabel('count')
    ax.set_ylim(0, (max(vals) if vals else 4) + 1)
    ax.legend(frameon=False, ncol=2)
    save(fig, 'batch_composition')

# ------------------------------------------------------- 9. LaTeX table ----
if SUMMARY:
    def fmt(k, scale=1, nd=2, unit=''):
        v = SUMMARY.get(k)
        if v is None:
            return '--'
        return f'{v / scale:,.{nd}f}{unit}'

    rows = [
        ('Window duration', fmt('window_hours', 1, 2, r'\,h')),
        ('Blocks produced (L2)', fmt('blocks_produced', 1, 0)),
        ('Blocks settled on L1', fmt('blocks_settled', 1, 0)),
        ('Production rate', fmt('production_rate_blocks_min', 1, 2, r'\,blocks/min')),
        ('Settlement rate', fmt('settlement_rate_blocks_min', 1, 2, r'\,blocks/min')),
        ('Settlement ratio', fmt('settlement_ratio', 1, 4)),
        ('Proofs generated', fmt('proofs_completed', 1, 0)),
        ('Proof generation time, mean', fmt('proof_time_mean_s', 1, 2, r'\,s')),
        ('Proof generation time, p50', fmt('proof_time_p50_s', 1, 2, r'\,s')),
        ('Proof generation time, p90', fmt('proof_time_p90_s', 1, 2, r'\,s')),
        ('Proof generation time, max', fmt('proof_time_max_s', 1, 2, r'\,s')),
        ('Proof size, mean', fmt('proof_size_mean_b', 2**20, 2, r'\,MiB')),
        ('Proof size, max', fmt('proof_size_max_b', 2**20, 2, r'\,MiB')),
        ('Proof batches, failed', fmt('batches_failed', 1, 0)),
        ('Ledger height spread, max', fmt('height_spread_max', 1, 0, r'\,blocks')),
        ('Ledger height spread, mean', fmt('height_spread_mean', 1, 2, r'\,blocks')),
        ('Validators reporting, min', fmt('validators_up_min', 1, 0)),
        ('Proving artefact growth', fmt('storage_gb_per_day', 1, 2, r'\,GiB/day')),
        ('Layer 2 database size', fmt('l2_db_size_b', 2**20, 2, r'\,MiB')),
    ]
    with open(os.path.join(ARGS.outdir, 'baseline_table.tex'), 'w') as f:
        f.write('% generated by plot.py - do not edit by hand\n')
        f.write('\\begin{tabular}{@{}lr@{}}\n\\toprule\n')
        f.write('\\textbf{Quantity} & \\textbf{Value} \\\\\n\\midrule\n')
        for k, v in rows:
            f.write(f'{k} & {v} \\\\\n')
        f.write('\\bottomrule\n\\end{tabular}\n')
    print(f'  {ARGS.outdir}/baseline_table.tex')

print('\ndone')
