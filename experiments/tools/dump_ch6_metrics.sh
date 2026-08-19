#!/usr/bin/env bash
# Dump all Chapter 6 metrics for the E1 + E2 campaign window (05/08/2026).
# E1 ran 09:36-10:36, E2 ran 11:10-13:07; window padded either side.
set -euo pipefail

START="2026-08-05T09:30:00Z"
END="2026-08-05T13:15:00Z"
STEP="30s"
OUT="$HOME/AppChain/results/ch6-metrics"

mkdir -p "$OUT"

dump() {
  local name="$1"
  local query="$2"
  echo "  $name"
  curl -sG 'http://localhost:9090/api/v1/query_range' \
    --data-urlencode "query=${query}" \
    --data-urlencode "start=${START}" \
    --data-urlencode "end=${END}" \
    --data-urlencode "step=${STEP}" \
    -o "${OUT}/${name}.json"
}

echo "dumping to ${OUT}"

# --- block production and settlement -------------------------------------
dump produced          'madara_block_produced_no'
dump settled           'madara_l1_block_number'

# --- proving -------------------------------------------------------------
dump proof_time        'proof_generation_seconds'
dump proof_time_madara 'madara_proof_generation_time_seconds'
dump proof_size        'proof_size_bytes'

# --- batch composition ---------------------------------------------------
dump batch_size        'proof_batch_size_transactions'
dump batches_total     'proof_batches_total'
dump batches_ok        'proof_batches_succeeded_total'
dump batches_failed    'proof_batches_failed_total'
dump snos_batches      'madara_batches_executed_batch_total'
dump batch_creation    'madara_batch_creation_total'

# --- accumulated storage -------------------------------------------------
dump storage_proofs    'gateway_storage_proofs_bytes'

# --- resource utilisation (per validator) --------------------------------
dump cpu               'rate(process_cpu_seconds_total{job="besu"}[5m])'
dump rss               'process_resident_memory_bytes{job="besu"}'

echo
echo "done. files:"
ls -la "$OUT"
echo
echo "now tar them up for upload:"
echo "  tar czf ~/ch6-metrics.tar.gz -C ${OUT} ."01~
