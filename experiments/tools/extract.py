#!/usr/bin/env python3
"""Extract the baseline window from Prometheus into CSV files.

Standard library only - runs anywhere Python 3.8+ does, no pip install.

    ./extract.py --hours 15 --out baseline
    ./extract.py --start 2026-08-03T20:00:00Z --end 2026-08-04T11:00:00Z --out baseline

Writes one CSV per measurement plus summary.json into the output directory.
Re-run it later against the same window and you get identical files, so the
figures in the dissertation can always be regenerated from the raw series.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

AP = argparse.ArgumentParser()
AP.add_argument('--prom', default='http://localhost:9090')
AP.add_argument('--hours', type=float, default=15.0)
AP.add_argument('--start', help='RFC3339, overrides --hours')
AP.add_argument('--end', help='RFC3339, defaults to now')
AP.add_argument('--step', default='30s')
AP.add_argument('--out', default='baseline')
ARGS = AP.parse_args()


def api(path, params):
    url = f"{ARGS.prom}/api/v1/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


end = (datetime.fromisoformat(ARGS.end.replace('Z', '+00:00')).timestamp()
       if ARGS.end else time.time())
start = (datetime.fromisoformat(ARGS.start.replace('Z', '+00:00')).timestamp()
         if ARGS.start else end - ARGS.hours * 3600)
WINDOW = f"{int((end - start) / 60)}m"

os.makedirs(ARGS.out, exist_ok=True)

# name -> (promql, label to use for column naming or None for single series)
RANGE_QUERIES = {
    # --- chain activity
    'blocks_produced':    ('madara_block_produced_no', None),
    'blocks_settled':     ('madara_l1_block_number', None),
    'settlement_lag':     ('madara_block_produced_no - madara_l1_block_number', None),

    # --- proving
    'proof_time':         ('proof_generation_seconds > 0', None),
    'proof_time_p50':     ('histogram_quantile(0.5, sum by (le) '
                           '(rate(proof_generation_seconds_histogram_bucket[10m])))', None),
    'proof_time_p90':     ('histogram_quantile(0.9, sum by (le) '
                           '(rate(proof_generation_seconds_histogram_bucket[10m])))', None),
    'proof_size':         ('proof_size_bytes > 0', None),
    'pie_zip_size':       ('madara_aggregator_pie_zip_bytes', None),
    'da_segment_size':    ('madara_aggregator_da_segment_bytes', None),

    # --- pipeline
    'batches_total':      ('proof_batches_total', None),
    'batches_succeeded':  ('proof_batches_succeeded_total', None),
    'batches_failed':     ('proof_batches_failed_total', None),
    'batch_size_pies':    ('proof_batch_size_transactions', None),
    'aggregator_children': ('madara_aggregator_child_count_children', None),
    'pipeline_backlog':   ('sum(madara_job_status_current{operation_job_status="Created"}) - '
                           'sum(madara_job_status_current{operation_job_status="Completed"})', None),
    'job_latency':        ('madara_job_e2e_latency_seconds', 'operation_job_type'),

    # --- layer 1
    'validator_height':   ('ethereum_blockchain_height{job="besu"}', 'node'),
    'height_spread':      ('max(ethereum_blockchain_height{job="besu"}) - '
                           'min(ethereum_blockchain_height{job="besu"})', None),
    'validators_up':      ('count(up{job="besu"} == 1)', None),
    'peer_count':         ('ethereum_peer_count{job="besu"}', 'node'),
    'l1_txpool':          ('besu_transaction_pool_number_of_transactions{job="besu"}', 'node'),

    # --- platform cost
    'validator_cpu':      ('rate(process_cpu_seconds_total{job="besu"}[5m])', 'node'),
    'validator_rss':      ('process_resident_memory_bytes{job="besu"}', 'node'),
    'storage_total':      ('gateway_storage_total_bytes', None),
    'storage_proofs':     ('gateway_storage_proofs_bytes', None),
    'storage_pies':       ('gateway_storage_pies_bytes', None),
    'storage_logs':       ('gateway_storage_logs_bytes', None),
    'storage_inputs':     ('gateway_storage_program_inputs_bytes', None),
    'l2_db_size':         ('madara_db_size', None),

    # --- workload
    'mempool_size':       ('madara_mempool_current_size_transaction', None),
    'txs_executed':       ('madara_txs_executed_tx_total', None),
}


def write_range(name, query, label):
    try:
        res = api('query_range', {'query': query, 'start': start,
                                  'end': end, 'step': ARGS.step})
    except Exception as e:
        print(f"  {name:<22} ERROR {e}")
        return 0
    series = res.get('data', {}).get('result', [])
    if not series:
        print(f"  {name:<22} (no data)")
        return 0

    # merge series onto a common timestamp axis
    cols, axis = {}, {}
    for s in series:
        col = s['metric'].get(label, 'value') if label else 'value'
        if col in cols:                      # duplicate label: disambiguate
            col = f"{col}_{len(cols)}"
        cols[col] = dict((int(t), v) for t, v in s['values'])
        axis.update({int(t): None for t, _ in s['values']})

    ts = sorted(axis)
    path = os.path.join(ARGS.out, f"{name}.csv")
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestamp', 'iso'] + list(cols))
        for t in ts:
            w.writerow([t, datetime.fromtimestamp(t, timezone.utc).isoformat()] +
                       [cols[c].get(t, '') for c in cols])
    print(f"  {name:<22} {len(ts):>6} rows  {len(cols)} col(s)")
    return len(ts)


print(f"window {datetime.fromtimestamp(start, timezone.utc).isoformat()} "
      f"-> {datetime.fromtimestamp(end, timezone.utc).isoformat()}  step={ARGS.step}")
print(f"output {ARGS.out}/\n")

for name, (query, label) in RANGE_QUERIES.items():
    write_range(name, query, label)

# ------------------------------------------------- proof time distribution --
# Histogram buckets as an instant query give the cumulative distribution of
# every proof in the window - the right input for a CDF or histogram figure.
print("\n  proof time distribution")
try:
    res = api('query', {'query':
              f'sum by (le) (increase(proof_generation_seconds_histogram_bucket[{WINDOW}]))'})
    rows = []
    for r in res['data']['result']:
        le = r['metric'].get('le', '+Inf')
        rows.append((float('inf') if le == '+Inf' else float(le),
                     float(r['value'][1])))
    rows.sort()
    with open(os.path.join(ARGS.out, 'proof_time_histogram.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['le_seconds', 'cumulative_count', 'bucket_count'])
        prev = 0.0
        for le, cum in rows:
            w.writerow(['inf' if le == float('inf') else le, cum, cum - prev])
            prev = cum
    print(f"    {len(rows)} buckets")
except Exception as e:
    print(f"    ERROR {e}")

# ------------------------------------------------------------- summary stats --
SUMMARY = {
    'blocks_produced':      f'increase(madara_block_produced_no[{WINDOW}])',
    'blocks_settled':       f'increase(madara_l1_block_number[{WINDOW}])',
    'lag_start':            f'min_over_time((madara_block_produced_no - madara_l1_block_number)[{WINDOW}:])',
    'lag_end':              'madara_block_produced_no - madara_l1_block_number',
    'proofs_completed':     f'increase(proof_generation_seconds_histogram_count[{WINDOW}])',
    'proof_time_mean_s':    f'increase(proof_generation_seconds_histogram_sum[{WINDOW}]) / '
                            f'clamp_min(increase(proof_generation_seconds_histogram_count[{WINDOW}]),1)',
    'proof_time_p50_s':     f'histogram_quantile(0.5, sum by (le) (rate(proof_generation_seconds_histogram_bucket[{WINDOW}])))',
    'proof_time_p90_s':     f'histogram_quantile(0.9, sum by (le) (rate(proof_generation_seconds_histogram_bucket[{WINDOW}])))',
    'proof_time_p99_s':     f'histogram_quantile(0.99, sum by (le) (rate(proof_generation_seconds_histogram_bucket[{WINDOW}])))',
    'proof_time_max_s':     f'max_over_time(proof_generation_seconds[{WINDOW}])',
    'proof_size_mean_b':    f'avg_over_time((proof_size_bytes > 0)[{WINDOW}:])',
    'proof_size_min_b':     f'min_over_time((proof_size_bytes > 0)[{WINDOW}:])',
    'proof_size_max_b':     f'max_over_time(proof_size_bytes[{WINDOW}])',
    'batches_total':        'proof_batches_total',
    'batches_failed':       'proof_batches_failed_total',
    'height_spread_max':    f'max_over_time((max(ethereum_blockchain_height{{job="besu"}}) - min(ethereum_blockchain_height{{job="besu"}}))[{WINDOW}:])',
    'height_spread_mean':   f'avg_over_time((max(ethereum_blockchain_height{{job="besu"}}) - min(ethereum_blockchain_height{{job="besu"}}))[{WINDOW}:])',
    'validators_up_min':    f'min_over_time((count(up{{job="besu"}} == 1))[{WINDOW}:])',
    'peers_min':            f'min_over_time(min(ethereum_peer_count{{job="besu"}})[{WINDOW}:])',
    'l1_blocks':            f'increase(max(ethereum_blockchain_height{{job="besu"}})[{WINDOW}:])',
    'storage_growth_b':     f'increase(gateway_storage_total_bytes[{WINDOW}])',
    'storage_total_b':      'gateway_storage_total_bytes',
    'l2_db_size_b':         'madara_db_size',
}

print("\n  summary")
summary = {'window_start': datetime.fromtimestamp(start, timezone.utc).isoformat(),
           'window_end': datetime.fromtimestamp(end, timezone.utc).isoformat(),
           'window_hours': round((end - start) / 3600, 3)}
for k, qy in SUMMARY.items():
    try:
        r = api('query', {'query': qy})['data']['result']
        summary[k] = float(r[0]['value'][1]) if r else None
    except Exception:
        summary[k] = None

# per-validator platform cost
for k, qy in {'cpu_cores': f'avg_over_time(rate(process_cpu_seconds_total{{job="besu"}}[5m])[{WINDOW}:])',
              'rss_bytes': f'max_over_time(process_resident_memory_bytes{{job="besu"}}[{WINDOW}])'}.items():
    try:
        summary[f'per_validator_{k}'] = {
            r['metric'].get('node', '?'): float(r['value'][1])
            for r in api('query', {'query': qy})['data']['result']}
    except Exception:
        summary[f'per_validator_{k}'] = None

# derived quantities
h = summary['window_hours']
if summary.get('blocks_produced') and h:
    summary['production_rate_blocks_min'] = round(summary['blocks_produced'] / (h * 60), 4)
if summary.get('blocks_settled') and h:
    summary['settlement_rate_blocks_min'] = round(summary['blocks_settled'] / (h * 60), 4)
if summary.get('blocks_produced') and summary.get('blocks_settled'):
    summary['settlement_ratio'] = round(summary['blocks_settled'] / summary['blocks_produced'], 4)
if summary.get('storage_growth_b') and h:
    summary['storage_gb_per_day'] = round(summary['storage_growth_b'] / 2**30 * 24 / h, 3)
if summary.get('proofs_completed') and summary.get('blocks_produced'):
    summary['blocks_per_proof'] = round(summary['blocks_produced'] / summary['proofs_completed'], 3)

with open(os.path.join(ARGS.out, 'summary.json'), 'w') as f:
    json.dump(summary, f, indent=2)

for k, v in summary.items():
    print(f"    {k:<30} {v}")
print(f"\nwritten to {ARGS.out}/")
