#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

RESUME=0
[ "${1:-}" = "--resume" ] && RESUME=1

DC="docker compose"
log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker not found"
command -v jq     >/dev/null || die "jq not found (sudo apt install jq)"

if [ "$RESUME" -eq 1 ]; then
  log "Resuming (no re-bootstrap)"
  [ -f output/base_addresses.json ] || die "no output/base_addresses.json — run ./up.sh fresh"
  if [ -f compose.dynamic.yaml ]; then
    $DC -f compose.yaml -f compose.dynamic.yaml up -d
  else
    $DC up -d
  fi
  ok "all services up"
  exit 0
fi

log "Tearing down previous run + wiping state"
if [ -f compose.dynamic.yaml ]; then
  $DC -f compose.yaml -f compose.dynamic.yaml --profile bootstrap down -v --remove-orphans || true
else
  $DC --profile bootstrap down -v --remove-orphans || true
fi
sudo rm -rf data output
rm -f compose.dynamic.yaml

# Founding validators: wipe chain state only. Their keys must survive —
# the matching addresses are baked into genesis.json extraData.
for v in validator1 validator2 validator3 validator4; do
  sudo rm -rf "./Layer1/besu/nodes/$v/data/database"
done

# Dynamically admitted validators: remove entirely. Their membership lived
# only in QBFT block headers, which this reset destroys, so the key is dead.
for d in ./Layer1/besu/nodes/*/; do
  [ -d "$d" ] || continue
  n="$(basename "$d")"
  case "$n" in
    validator1|validator2|validator3|validator4) ;;
    *) printf '  removing dynamic validator node %s\n' "$n"; sudo rm -rf "$d" ;;
  esac
done
mkdir -p data/madara data/pathfinder data/madara-fullnode output
sed -i 's/^eth_core_contract_address:.*/eth_core_contract_address: "0x0000000000000000000000000000000000000000"/' configs/madara.yaml
sed -i 's/^MADARA_ORCHESTRATOR_MOCK_VERIFIER_ADDRESS=.*/MADARA_ORCHESTRATOR_MOCK_VERIFIER_ADDRESS=__VERIFIER_ADDRESS__/' orchestrator.env
sed -i 's/^MADARA_ORCHESTRATOR_L1_CORE_CONTRACT_ADDRESS=.*/MADARA_ORCHESTRATOR_L1_CORE_CONTRACT_ADDRESS=__CORE_CONTRACT_ADDRESS__/' orchestrator.env
ok "clean"

log "Step 1/9  Infrastructure"
$DC up -d besu-validator1 besu-validator2 besu-validator3 besu-validator4 mongodb localstack
for svc in besu-validator1 mongodb localstack; do
  printf '  waiting for %s' "$svc"
  for _ in $(seq 1 60); do
    state=$(docker inspect -f '{{.State.Health.Status}}' "ds-$svc" 2>/dev/null || echo starting)
    [ "$state" = "healthy" ] && { printf ' healthy\n'; break; }
    printf '.'; sleep 2
  done
  [ "$(docker inspect -f '{{.State.Health.Status}}' "ds-$svc" 2>/dev/null)" = "healthy" ] || die "$svc never healthy"
done

log "Step 2/9  Starting Telemetry (OTel Collector)"
$DC up -d otel-collector
printf '  waiting for otel-collector'
for _ in $(seq 1 30); do
  state=$(docker inspect -f '{{.State.Status}}' ds-otel-collector 2>/dev/null || echo starting)
  [ "$state" = "running" ] && { printf ' running\n'; break; }
  printf '.'; sleep 2
done
ok "otel-collector up"

log "Step 3/9  Provisioning LocalStack"
$DC --profile bootstrap run --rm orchestrator-setup || die "orchestrator setup failed"
ok "LocalStack provisioned"

log "Step 4/9  Deploying MockGPSVerifier"
_IMG=$(grep -E "^FOUNDRY_IMAGE=" .env | cut -d= -f2-)
_KEY=$(grep -E "^ANVIL_PRIVATE_KEY=" .env | cut -d= -f2-)
docker run --rm \
  --entrypoint "" \
  --network drone_swarm_appchain \
  -v "$(pwd)/helper:/helper:ro" \
  -v "$(pwd)/output:/output" \
  "$_IMG" \
  /bin/sh /helper/deploy_verifier.sh http://besu-validator1:8545 "$_KEY" \
  || die "verifier deploy failed"
[ -s output/verifier_address.txt ] || die "verifier_address.txt empty"
VERIFIER_ADDR=$(cat output/verifier_address.txt)
ok "verifier @ $VERIFIER_ADDR"
jq --arg v "$VERIFIER_ADDR" \
   '.base_layer.core_contract_init_data.verifier = $v' \
   configs/bootstrapper_v2.json > configs/bootstrapper_v2.json.tmp \
   && mv configs/bootstrapper_v2.json.tmp configs/bootstrapper_v2.json
sed -i "s|^MADARA_ORCHESTRATOR_MOCK_VERIFIER_ADDRESS=.*|MADARA_ORCHESTRATOR_MOCK_VERIFIER_ADDRESS=$VERIFIER_ADDR|" orchestrator.env

log "Step 5/9  bootstrapper-v2 setup-base"
$DC --profile bootstrap run --rm bootstrap-base || die "setup-base failed"
[ -s output/base_addresses.json ] || die "base_addresses.json not produced"
CORE_ADDR=$(jq -r '.addresses.coreContract' output/base_addresses.json)
[ "$CORE_ADDR" != "null" ] && [ -n "$CORE_ADDR" ] || die "coreContract missing in base_addresses.json"
ok "core contract @ $CORE_ADDR"
sed -i "s|^eth_core_contract_address:.*|eth_core_contract_address: \"$CORE_ADDR\"|" configs/madara.yaml
sed -i "s|^MADARA_ORCHESTRATOR_L1_CORE_CONTRACT_ADDRESS=.*|MADARA_ORCHESTRATOR_L1_CORE_CONTRACT_ADDRESS=$CORE_ADDR|" orchestrator.env
ok "core contract patched into madara.yaml + orchestrator.env"

cast send --rpc-url http://localhost:8545 \
  --private-key 0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a \
  "$CORE_ADDR" "starknetAcceptGovernance()" >/dev/null
cast send --rpc-url http://localhost:8545 \
  --private-key 0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a \
  "$CORE_ADDR" "registerOperator(address)" 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 >/dev/null
ok "account #0 registered as operator on core contract"

log "Step 6/9  Starting Madara (--no-charge-fee for bootstrap)"
$DC -f compose.yaml -f compose.bootstrap-override.yaml up -d madara
printf '  waiting for madara'
for _ in $(seq 1 90); do
  state=$(docker inspect -f '{{.State.Health.Status}}' ds-madara 2>/dev/null || echo starting)
  [ "$state" = "healthy" ] && { printf ' healthy\n'; break; }
  printf '.'; sleep 2
done
[ "$(docker inspect -f '{{.State.Health.Status}}' ds-madara 2>/dev/null)" = "healthy" ] \
  || die "madara never healthy — check: docker logs ds-madara"

log "Step 7/9  bootstrapper-v2 setup-madara"
printf '  waiting for Madara to produce block 1'
for _ in $(seq 1 60); do
  BN=$(curl -sf -X POST http://localhost:9944 \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"starknet_blockNumber","params":[],"id":1}' \
    2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',0))" 2>/dev/null || echo 0)
  [ "${BN:-0}" -ge 1 ] 2>/dev/null && { printf ' block %s\n' "$BN"; break; }
  printf '.'; sleep 3
done
[ "${BN:-0}" -ge 1 ] 2>/dev/null || die "Madara did not produce a block in time"
$DC --profile bootstrap run --rm bootstrap-madara || die "setup-madara failed"
[ -s output/madara_addresses.json ] && ok "L2 addresses written to output/madara_addresses.json"

log "Step 8/9  Starting Pathfinder + Stwo Gateway + Orchestrator"
$DC up -d pathfinder
printf '  giving pathfinder ~20s to begin syncing'
for _ in $(seq 1 10); do printf '.'; sleep 2; done
printf '\n'
ok "pathfinder started"

$DC up -d stwo-gateway
ok "stwo-gateway started"

$DC up -d orchestrator
ok "orchestrator started"

log "  Restarting Madara without --no-charge-fee"
$DC stop madara
$DC up -d madara
printf '  waiting for madara'
for _ in $(seq 1 60); do
  state=$(docker inspect -f '{{.State.Health.Status}}' ds-madara 2>/dev/null || echo starting)
  [ "$state" = "healthy" ] && { printf ' healthy\n'; break; }
  printf '.'; sleep 2
done
[ "$(docker inspect -f '{{.State.Health.Status}}' ds-madara 2>/dev/null)" = "healthy" ] \
  || die "madara failed to restart without --no-charge-fee"
ok "Madara restarted — fee charging enabled"

log "Step 9/9  Starting Prometheus + Grafana + Full Node"
$DC up -d prometheus grafana besu-exporter
ok "prometheus + grafana started"

$DC up -d madara-fullnode
ok "madara-fullnode started"

cat << 'BANNER'

============================================================
 DroneSwarm appchain is up.

   L2 RPC ......... http://localhost:9944
   L2 admin ....... http://localhost:9943
   Gateway ........ http://localhost:8080
   Pathfinder ..... http://localhost:9545
   Full node ...... http://localhost:9946
   Orchestrator ... http://localhost:3000
   L1 (Besu) ..... http://localhost:8545
   Grafana ........ http://localhost:3001  (admin / droneswarm)
   Prometheus ..... http://localhost:9090

 Watch: docker compose logs -f orchestrator
 Stop:  docker compose stop
 Resume: ./up.sh --resume
 Teardown: ./down.sh
============================================================
BANNER

printf "   Core contract . %s\n" "$CORE_ADDR"
printf "   Verifier ...... %s\n\n" "$VERIFIER_ADDR"
