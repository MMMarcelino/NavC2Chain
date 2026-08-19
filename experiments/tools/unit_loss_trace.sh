#!/bin/bash
OUT="${1:?usage: unit_loss_trace.sh <output-file>}"
echo "timestamp_utc l1_heights l2_produced l2_settled" | tee -a "$OUT"
while true; do
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  l1=$(curl -s http://localhost:9090/api/v1/query --data-urlencode 'query=ethereum_blockchain_height{job="besu"}' | jq -r '[.data.result[] | "\(.metric.node)=\(.value[1])"] | join(",")')
  l2=$(curl -s http://localhost:9090/api/v1/query --data-urlencode 'query=madara_block_produced_no' | jq -r '.data.result[0].value[1] // "NA"')
  settled=$(curl -s http://localhost:9090/api/v1/query --data-urlencode 'query=madara_l1_block_number' | jq -r '.data.result[0].value[1] // "NA"')
  echo "$ts $l1 $l2 $settled" | tee -a "$OUT"
  sleep 5
done
