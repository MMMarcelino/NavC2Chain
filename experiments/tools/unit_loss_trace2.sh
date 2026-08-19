#!/bin/bash
OUT="${1:?usage: unit_loss_trace2.sh <output-file> <contract-address>}"
CONTRACT="${2:?usage: unit_loss_trace2.sh <output-file> <contract-address>}"
echo "timestamp_utc l1_heights l2_produced l2_settled" | tee -a "$OUT"
i=0
while true; do
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  l1=$(curl -s http://localhost:9090/api/v1/query --data-urlencode 'query=ethereum_blockchain_height{job="besu"}' | jq -r '[.data.result[] | "\(.metric.node)=\(.value[1])"] | sort | join(",")')
  l2=$(curl -s http://localhost:9090/api/v1/query --data-urlencode 'query=madara_block_produced_no' | jq -r '.data.result[0].value[1] // "NA"')
  settled=$(curl -s http://localhost:9090/api/v1/query --data-urlencode 'query=madara_l1_block_number' | jq -r '.data.result[0].value[1] // "NA"')
  echo "$ts $l1 $l2 $settled" | tee -a "$OUT"
  if [ $((i % 12)) -eq 0 ]; then
    tr=$(timeout 20 sncast call --contract-address "$CONTRACT" --function total_reports --url http://localhost:9944 2>/dev/null | grep -oE '0x[0-9a-fA-F]+' | tail -1)
    echo "# TOTAL_REPORTS $ts ${tr:-QUERY_FAILED}" | tee -a "$OUT"
  fi
  i=$((i+1))
  sleep 5
done
