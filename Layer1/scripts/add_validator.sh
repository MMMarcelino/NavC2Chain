#!/usr/bin/env bash
# add_validator.sh — Add a new QBFT validator node to the DroneSwarm L1
# Usage: ./add_validator.sh <validator_name> <ip_last_octet>
# Example: ./add_validator.sh validator5 15
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APPCHAIN_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BESU_DIR="$APPCHAIN_DIR/Layer1/besu"
COMPOSE_FILE="$APPCHAIN_DIR/compose.yaml"
DYNAMIC_FILE="$APPCHAIN_DIR/compose.dynamic.yaml"

BOOTNODE_ENODE="enode://dc76e6b0726de575578083be78c894b0cef638c1d05bfe38f6cb8f2d02822f7010fc08c59fabd717cd9410b6a8f808319f4d4ef86a29cd1ea2c6245c147eebe1@172.30.0.11:30303"

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

# --- Validate arguments ---
[ $# -eq 2 ] || die "Usage: $0 <validator_name> <ip_last_octet>   (example: $0 validator5 15)"
NAME="$1"
OCTET="$2"
IP="172.30.0.$OCTET"
NODE_DIR="$BESU_DIR/nodes/$NAME"
SERVICE="besu-$NAME"
CONTAINER="ds-$SERVICE"

# --- Remove partial state if we die part-way through ---
TMPGEN=""
NODE_DIR_CREATED=0
cleanup() {
  local rc=$?
  [ $rc -eq 0 ] && return 0
  if [ -n "$TMPGEN" ] && [ -d "$TMPGEN" ]; then
    rm -rf "$TMPGEN" 2>/dev/null || sudo rm -rf "$TMPGEN" 2>/dev/null || \
      printf '\033[1;33m  warn\033[0m could not remove %s (root-owned?) — clean up manually\n' "$TMPGEN" >&2
  fi
  if [ "$NODE_DIR_CREATED" -eq 1 ]; then
    rm -rf "$NODE_DIR" 2>/dev/null && \
      printf '\033[1;33m  cleaned\033[0m removed partial node dir %s\n' "$NODE_DIR" >&2
  fi
  return $rc
}
trap cleanup EXIT

# --- Check for conflicts in both files ---
[ -d "$NODE_DIR" ] && die "Node directory already exists: $NODE_DIR"
grep -q "container_name: $CONTAINER" "$COMPOSE_FILE" && die "Service $SERVICE already exists in compose.yaml"
[ -f "$DYNAMIC_FILE" ] && grep -q "container_name: $CONTAINER" "$DYNAMIC_FILE" && die "Service $SERVICE already exists in compose.dynamic.yaml"
grep -q "ipv4_address: $IP" "$COMPOSE_FILE" && die "IP $IP already in use in compose.yaml"
[ -f "$DYNAMIC_FILE" ] && grep -q "ipv4_address: $IP" "$DYNAMIC_FILE" && die "IP $IP already in use in compose.dynamic.yaml"

# --- Check dependencies ---
command -v docker >/dev/null || die "docker not found"

log "Generating key for $NAME"
mkdir -p "$NODE_DIR/data"
NODE_DIR_CREATED=1

BESU_IMAGE="hyperledger/besu:26.4.0@sha256:12e256a73185337f2d09fa00c6a979d9ce9a8aac4ec1e173c43f3ef88443a799"
TMPGEN="$(mktemp -d "$BESU_DIR/.keygen.XXXXXX")"

cat > "$TMPGEN/config.json" << 'JSON'
{
  "genesis": {
    "config": { "chainId": 31337, "qbft": { "blockperiodseconds": 2, "epochlength": 30000, "requesttimeoutseconds": 4 } },
    "nonce": "0x0",
    "gasLimit": "0x1fffffffffffff",
    "difficulty": "0x1",
    "alloc": {}
  },
  "blockchain": { "nodes": { "generate": true, "count": 1 } }
}
JSON

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$TMPGEN:/keygen" \
  "$BESU_IMAGE" \
  operator generate-blockchain-config \
  --config-file=/keygen/config.json \
  --to=/keygen/out \
  --private-key-file-name=key \
  || true
# besu's operator tool has been observed to throw
# "Output directory already exists" and exit 1 even on a fresh directory,
# AFTER writing valid output. Exit code is unreliable here — check for the
# actual artifact instead of trusting it.

KEYDIR="$(find "$TMPGEN/out/keys" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)"
[ -n "$KEYDIR" ] || die "Key generation failed — no key directory produced (operator generate-blockchain-config)"

ADDRESS="$(basename "$KEYDIR")"
cp "$KEYDIR/key"     "$NODE_DIR/data/key"
cp "$KEYDIR/key.pub" "$NODE_DIR/data/key.pub"
rm -rf "$TMPGEN"

[ -f "$NODE_DIR/data/key" ]     || die "Key copy failed — key not found"
[ -f "$NODE_DIR/data/key.pub" ] || die "Key copy failed — key.pub not found"
ok "Key generated at $NODE_DIR/data/key"

[ -n "$ADDRESS" ] || die "Could not derive address from key"
ok "Validator address: $ADDRESS"

# --- Propose validator via QBFT API (if chain is running) ---
if docker ps --format '{{.Names}}' | grep -q "ds-besu-validator1"; then
  log "Chain is running — proposing $ADDRESS as new validator"
  VOTE_RESP="$(curl -s -X POST http://localhost:8545 \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"qbft_proposeValidatorVote\",\"params\":[\"$ADDRESS\",true],\"id\":1}" \
    || true)"
  case "$VOTE_RESP" in
    *'"result":true'*) ok "Vote cast by validator1 (PT)" ;;
    "")  die "No response from validator1 RPC on localhost:8545 — vote NOT cast" ;;
    *)   die "validator1 rejected the vote: $VOTE_RESP" ;;
  esac
  echo ""
  echo "  NOTE: A majority of existing validators must also vote to add $ADDRESS."
  echo "  Validators 2+ have no host-published RPC port and no curl in the image,"
  echo "  so send each vote from a disposable container on the internal network:"
  echo ""
  echo "  docker run --rm --network drone_swarm_appchain curlimages/curl -s -X POST \\"
  echo "    http://besu-validatorN:8545 -H 'Content-Type: application/json' \\"
  echo "    -d '{\"jsonrpc\":\"2.0\",\"method\":\"qbft_proposeValidatorVote\",\"params\":[\"$ADDRESS\",true],\"id\":1}'"
  echo ""
  echo "  Then confirm admission:"
  echo "  curl -s -X POST http://localhost:8545 -H 'Content-Type: application/json' \\"
  echo "    -d '{\"jsonrpc\":\"2.0\",\"method\":\"qbft_getValidatorsByBlockNumber\",\"params\":[\"latest\"],\"id\":1}'"
else
  log "Chain not running — skipping validator proposal"
fi

# --- Create dynamic file header if it doesn't exist ---
if [ ! -f "$DYNAMIC_FILE" ]; then
  cat > "$DYNAMIC_FILE" << 'HEADER'
services:
HEADER
fi

# --- Append new service to dynamic file ---
log "Adding $SERVICE service to compose.dynamic.yaml"
cat >> "$DYNAMIC_FILE" << YAML

  $SERVICE:
    image: $BESU_IMAGE
    container_name: $CONTAINER
    volumes:
      - ./Layer1/besu/config.toml:/config/config.toml:ro
      - ./Layer1/besu/genesis.json:/config/genesis.json:ro
      - ./Layer1/besu/nodes/$NAME/data:/opt/besu/data
    command:
      - --config-file=/config/config.toml
      - --bootnodes=$BOOTNODE_ENODE
      - --metrics-enabled
      - --metrics-host=0.0.0.0
      - --metrics-port=9545
      - --metrics-category=BLOCKCHAIN,ETHEREUM,PEERS,TRANSACTION_POOL,SYNCHRONIZER,PROCESS,JVM
    depends_on:
      besu-validator1:
        condition: service_healthy
    networks:
      appchain:
        ipv4_address: $IP
YAML
ok "Service block added to compose.dynamic.yaml"

log "Done! New validator summary:"
echo "  Name     : $NAME"
echo "  Service  : $SERVICE"
echo "  Container: $CONTAINER"
echo "  Address  : $ADDRESS"
echo "  IP       : $IP"
echo "  Key      : $NODE_DIR/data/key"
echo ""
echo "Next steps:"
echo "  1. A majority of existing validators must also vote for $ADDRESS"
echo "  2. Start: docker compose -f compose.yaml -f compose.dynamic.yaml up -d $SERVICE"
echo "  3. Scrape it: add '$SERVICE:9545' to the besu job in configs/prometheus.yaml"
echo "  4. On resume (./up.sh --resume), the node starts automatically"
echo "  5. On fresh start (./up.sh), node dir, key and compose entry are all removed"
