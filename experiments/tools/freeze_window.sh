#!/usr/bin/env bash
# freeze_window.sh <label> <startZ> <endZ>
# Exports the Prometheus window + Mongo job records for a run to CSV/JSONL,
# so the data survives a stack restart. Run BEFORE restarting anything.
#   ./freeze_window.sh patrol-r5 2026-08-21T09:00:00Z 2026-08-21T14:00:00Z
set -euo pipefail

[ $# -eq 3 ] || { echo "usage: $0 <label> <startZ> <endZ>"; exit 1; }
L=$1; S=$2; E=$3
case "$S$E" in *Z*Z) ;; *) echo "timestamps must end in Z (UTC)"; exit 1;; esac

PROM=localhost:9090
D=~/AppChain/experiments/extracts/$L
mkdir -p "$D"
echo "freezing $L  $S -> $E"

curl -sf "$PROM/-/healthy" >/dev/null || { echo "prometheus unreachable"; exit 1; }

STEP=${STEP:-30s}

declare -A Q=(
 [blocks_produced]='madara_block_produced_no'
 [blocks_settled]='madara_l1_block_number'
 [proof_time]='proof_generation_seconds'
 [proof_size]='proof_size_bytes'
 [proof_hist_sum]='proof_generation_seconds_histogram_sum'
 [proof_hist_count]='proof_generation_seconds_histogram_count'
 [batches_succeeded]='proof_batches_succeeded_total'
 [batches_failed]='proof_batches_failed_total'
 [batch_size_pies]='proof_batch_size_transactions'
 [aggregator_children]='madara_aggregator_child_count_children'
 [queue_wait]='madara_job_queue_wait_time_seconds'
 [mempool_size]='madara_mempool_current_size_transaction'
 [storage_proofs]='gateway_storage_proofs_bytes'
 [validator_height]='ethereum_blockchain_height{job="besu"}'
 [validators_up]='up{job="besu"}'
 [peer_count]='ethereum_peer_count{job="besu"}'
 [l1_txpool]='besu_transaction_pool_number_of_transactions'
 [validator_cpu]='rate(process_cpu_seconds_total{job="besu"}[5m])'
 [validator_rss]='process_resident_memory_bytes{job="besu"}'
 [validator_heap]='jvm_memory_used_bytes{job="besu",area="heap"}'
)

empty=0
for k in $(printf '%s\n' "${!Q[@]}" | sort); do
  curl -s --get "$PROM/api/v1/query_range" \
    --data-urlencode "query=${Q[$k]}" \
    --data-urlencode "start=$S" --data-urlencode "end=$E" \
    --data-urlencode "step=$STEP" \
  | jq -r '.data.result[]? | (.metric.node // .metric.instance // "-") as $n
           | .values[] | [$n, .[0], .[1]] | @csv' \
  | sed '1i node,timestamp,value' > "$D/$k.csv"
  n=$(( $(wc -l < "$D/$k.csv") - 1 ))
  printf '  %-22s %6d rows\n' "$k" "$n"
  [ "$n" -eq 0 ] && empty=$((empty+1))
done

# Mongo job records — full documents, filtered by window
( cd ~/AppChain && docker compose exec -T mongodb mongosh --quiet --eval "
  db.getSiblingDB('orchestrator').jobs.find(
    {updated_at:{\$gte:ISODate('$S'), \$lte:ISODate('$E')}}
  ).sort({job_type:1, internal_id:1}).forEach(d=>print(JSON.stringify(d)))" ) \
  > "$D/jobs.jsonl" 2>"$D/jobs.err" || true
echo "  jobs.jsonl             $(wc -l < "$D/jobs.jsonl") documents"

# provenance — the things that silently become "findings" later
{
  echo "label=$L"; echo "start=$S"; echo "end=$E"; echo "step=$STEP"
  echo "frozen_at=$(date -u +%FT%TZ)"
  echo "node=$(node -v 2>/dev/null || echo n/a)"
  echo "driver_sha=$(git -C ~/AppChain rev-parse --short HEAD 2>/dev/null || echo n/a)"
  echo "driver_dirty=$(git -C ~/AppChain status --porcelain 2>/dev/null | wc -l)"
  echo "prom_min_time=$(curl -s $PROM/api/v1/status/tsdb | jq -r '.data.headStats.minTime')"
  echo "containers=$(docker ps --format '{{.Names}}' | sort | tr '\n' ' ')"
} > "$D/provenance.txt"

# copy driver artefacts + trace if they match the label
cp ~/AppChain/experiments/driver/runs/${L}-*.jsonl        "$D/" 2>/dev/null || true
cp ~/AppChain/experiments/driver/runs/${L}-*.summary.json "$D/" 2>/dev/null || true
cp ~/AppChain/${L}_trace.log                              "$D/" 2>/dev/null || true

echo "frozen to $D"
[ "$empty" -gt 0 ] && echo "WARNING: $empty series came back empty — check names before restarting"
exit 0
