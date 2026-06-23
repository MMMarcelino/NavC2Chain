#!/bin/bash

CONTRACT="0x065a7e2c7f2e28f317fad7b362657d0c3447064bc56f3d30d54b99239170c461"
URL="http://localhost:9944"
ACCOUNTS=("PTDrone" "ESDrone" "FRDrone" "UKDrone")
INTERVAL=${1:-15}  # seconds between rounds, default 15

echo "================================================"
echo "NavC2Chain Load Test"
echo "Contract : $CONTRACT"
echo "Accounts : ${ACCOUNTS[*]}"
echo "Interval : ${INTERVAL}s"
echo "Press Ctrl+C to stop"
echo "================================================"

round=0
total_tx=0
start_time=$(date +%s)

while true; do
    round=$((round + 1))
    round_start=$(date +%s%3N)
    echo ""
    echo "[$(date +%T)] Round $round — firing ${#ACCOUNTS[@]} transactions"

    pids=()
    for account in "${ACCOUNTS[@]}"; do
        sncast --account $account invoke \
            --url $URL \
            --contract-address $CONTRACT \
            --function increase \
            --calldata 1 > /tmp/sncast_${account}.log 2>&1 &
        pids+=($!)
    done

    # wait for all to complete
    for pid in "${pids[@]}"; do
        wait $pid
    done

    round_end=$(date +%s%3N)
    round_ms=$((round_end - round_start))
    total_tx=$((total_tx + ${#ACCOUNTS[@]}))
    elapsed=$(( (round_end / 1000) - start_time ))
    tps=$(echo "scale=2; $total_tx / $elapsed" | bc)

    echo "[$(date +%T)] Round $round done in ${round_ms}ms | Total txs: $total_tx | Avg TPS: $tps"

    # print any errors
    for account in "${ACCOUNTS[@]}"; do
        if grep -q "Error\|error" /tmp/sncast_${account}.log 2>/dev/null; then
            echo "  [$account] ERROR: $(cat /tmp/sncast_${account}.log | tail -1)"
        fi
    done

    sleep $INTERVAL
done
