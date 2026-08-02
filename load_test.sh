#!/bin/bash
# NavC2Chain load driver
# usage: ./load_test.sh [INTERVAL_SECONDS] [RUN_ID]
#   env overrides: CONTRACT, URL, INTERVAL, RUN_ID

CONTRACT="0x05341460613e3de212c2dc21d8df1b6948c6e953e1ad93a63e5f6e86bd8229f4"
URL="${URL:-http://localhost:9944}"
ACCOUNTS=("PTDrone" "ESDrone" "FRDrone" "UKDrone")
INTERVAL="${INTERVAL:-${1:-15}}"
RUN_ID="${RUN_ID:-${2:-adhoc}}"

OUTDIR="results/$RUN_ID"; mkdir -p "$OUTDIR"
CSV="$OUTDIR/driver.csv"
[ -f "$CSV" ] || echo "utc_ts,epoch,round,txs_total,round_ms,errors" > "$CSV"

rpc() { curl -s -X POST "$URL" -H 'Content-Type: application/json' \
        -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}"; }

echo "=== NavC2Chain Load Test ==="
echo "Contract : $CONTRACT"
echo "URL      : $URL"
echo "Interval : ${INTERVAL}s   Run: $RUN_ID"

# ---- preflight -------------------------------------------------------------
if [ "$CONTRACT" = "0xREPLACE_ME" ]; then
  echo "FATAL: set CONTRACT at the top of the script"; exit 1
fi
if ! rpc starknet_getClassHashAt "[\"latest\",\"$CONTRACT\"]" | grep -q '"result"'; then
  echo "FATAL: contract $CONTRACT not found on this chain (stale address?)"; exit 1
fi
for a in "${ACCOUNTS[@]}"; do
  addr=$(sncast account list 2>/dev/null | grep -A8 -- "- ${a}:" | awk '$1=="address:"{print $2; exit}')
  if [ -z "$addr" ]; then echo "FATAL: $a not in sncast registry"; exit 1; fi
  if ! rpc starknet_getNonce "[\"latest\",\"$addr\"]" | grep -q '"result"'; then
    echo "FATAL: $a ($addr) not deployed on this chain"; exit 1
  fi
done
echo "preflight OK — contract and ${#ACCOUNTS[@]} accounts live"
echo "logging to $CSV"
echo "Ctrl+C to stop"

# ---- main loop -------------------------------------------------------------
round=0; total_tx=0; err_total=0; start_time=$(date +%s)
trap 'el=$(( $(date +%s)-start_time )); [ $el -eq 0 ] && el=1;
      echo; echo "=== stopped: $total_tx tx in ${el}s = $(awk -v t=$total_tx -v e=$el "BEGIN{printf \"%.2f\", t/e}") tx/s, $err_total errors ===";
      exit 0' INT TERM

while true; do
  round=$((round+1)); rs=$(date +%s%3N); pids=()
  for a in "${ACCOUNTS[@]}"; do
    sncast --account "$a" invoke --url "$URL" \
      --contract-address "$CONTRACT" --function report_position --calldata 4123456 8912345 10000 0x4f4b \
      > "/tmp/sncast_${a}.log" 2>&1 &
    pids+=($!)
  done
  fails=0
  for p in "${pids[@]}"; do wait "$p" || fails=$((fails+1)); done
  re=$(date +%s%3N); rms=$((re-rs))
  total_tx=$((total_tx+${#ACCOUNTS[@]})); err_total=$((err_total+fails))
  el=$(( (re/1000)-start_time )); [ $el -eq 0 ] && el=1
  tps=$(awk -v t=$total_tx -v e=$el 'BEGIN{printf "%.2f", t/e}')
  echo "[$(date -u +%T)] r$round ${rms}ms | total=$total_tx | avg=${tps} tx/s | err=$fails"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ),$(date -u +%s),$round,$total_tx,$rms,$fails" >> "$CSV"
  [ "$fails" -gt 0 ] && for a in "${ACCOUNTS[@]}"; do
      grep -qi 'error' "/tmp/sncast_${a}.log" && echo "   [$a] $(tail -1 "/tmp/sncast_${a}.log")"
    done
  sleep "$INTERVAL"
done
