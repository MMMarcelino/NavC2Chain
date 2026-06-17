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
[ $# -eq 2 ] || die "Usage: $0 <validator_name> <ip_last_octet>\n  Example: $0 validator5 15"
NAME="$1"
OCTET="$2"
IP="172.30.0.$OCTET"
NODE_DIR="$BESU_DIR/nodes/$NAME"

# --- Check for conflicts in both files ---
[ -d "$NODE_DIR" ] && die "Node directory already exists: $NODE_DIR"
grep -q "container_name: ds-$NAME" "$COMPOSE_FILE" && die "Service $NAME already exists in compose.yaml"
[ -f "$DYNAMIC_FILE" ] && grep -q "container_name: ds-$NAME" "$DYNAMIC_FILE" && die "Service $NAME already exists in compose.dynamic.yaml"
grep -q "ipv4_address: $IP" "$COMPOSE_FILE" && die "IP $IP already in use in compose.yaml"
[ -f "$DYNAMIC_FILE" ] && grep -q "ipv4_address: $IP" "$DYNAMIC_FILE" && die "IP $IP already in use in compose.dynamic.yaml"

# --- Check dependencies ---
command -v docker >/dev/null || die "docker not found"

log "Generating key for $NAME"
mkdir -p "$NODE_DIR/data"

docker run --rm \
  -v "$NODE_DIR/data:/opt/besu/data" \
  hyperledger/besu:latest \
  operator generate-key-pair \
  --to=/opt/besu/data/key \
  >/dev/null 2>&1

[ -f "$NODE_DIR/data/key" ]     || die "Key generation failed — key not found"
[ -f "$NODE_DIR/data/key.pub" ] || die "Key generation failed — key.pub not found"
ok "Key generated at $NODE_DIR/data/key"

# --- Get the new validator's address ---
ADDRESS=$(docker run --rm \
  -v "$NODE_DIR/data:/opt/besu/data" \
  hyperledger/besu:latest \
  public-key export-address \
  --node-private-key-file=/opt/besu/data/key \
  2>/dev/null | grep -oE '0x[0-9a-fA-F]{40}' | tail -1)

[ -n "$ADDRESS" ] || die "Could not derive address from key"
ok "Validator address: $ADDRESS"

# --- Propose validator via QBFT API (if chain is running) ---
if docker ps --format '{{.Names}}' | grep -q "ds-besu-validator1"; then
  log "Chain is running — proposing $ADDRESS as new validator"
  for port in 8545; do
    curl -sf -X POST http://localhost:$port \
      -H "Content-Type: application/json" \
      -d "{\"jsonrpc\":\"2.0\",\"method\":\"qbft_proposeValidatorVote\",\"params\":[\"$ADDRESS\",true],\"id\":1}" \
      >/dev/null && ok "Vote proposed on validator1 (port $port)"
  done
  echo ""
  echo "  NOTE: All other running validators must also vote to add $ADDRESS."
  echo "  Run this on each validator container:"
  echo "  curl -X POST http://localhost:8545 -H 'Content-Type: application/json' \\"
  echo "    -d '{\"jsonrpc\":\"2.0\",\"method\":\"qbft_proposeValidatorVote\",\"params\":[\"$ADDRESS\",true],\"id\":1}'"
else
  log "Chain not running — skipping validator proposal"
fi

# --- Create dynamic file header if it doesn't exist ---
if [ ! -f "$DYNAMIC_FILE" ]; then
  cat > "$DYNAMIC_FILE" << HEADER
services:
HEADER
fi

# --- Append new service to dynamic file ---
log "Adding $NAME service to compose.dynamic.yaml"
cat >> "$DYNAMIC_FILE" << YAML

  $NAME:
    image: hyperledger/besu:latest
    container_name: ds-$NAME
    volumes:
      - ./Layer1/besu/config.toml:/config/config.toml:ro
      - ./Layer1/besu/genesis.json:/config/genesis.json:ro
      - ./Layer1/besu/nodes/$NAME/data:/opt/besu/data
    command:
      - --config-file=/config/config.toml
      - --bootnodes=$BOOTNODE_ENODE
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
echo "  Address  : $ADDRESS"
echo "  IP       : $IP"
echo "  Key      : $NODE_DIR/data/key"
echo ""
echo "Next steps:"
echo "  1. If chain is running: ensure all existing validators vote for $ADDRESS"
echo "  2. Start: docker compose -f compose.yaml -f compose.dynamic.yaml up -d $NAME"
echo "  3. On resume (./up.sh --resume), the node will start automatically"
echo "  4. On fresh start (./up.sh), the node will be removed"
