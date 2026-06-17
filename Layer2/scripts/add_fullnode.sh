#!/usr/bin/env bash
# add_fullnode.sh — Add a new Madara full node to the DroneSwarm L2
# Usage: ./add_fullnode.sh <node_name> <rpc_port>
# Example: ./add_fullnode.sh vessel-frigate 9947
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APPCHAIN_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$APPCHAIN_DIR/compose.yaml"
DYNAMIC_FILE="$APPCHAIN_DIR/compose.dynamic.yaml"

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

# --- Validate arguments ---
[ $# -eq 2 ] || die "Usage: $0 <node_name> <rpc_port>\n  Example: $0 vessel-frigate 9947"
NAME="$1"
PORT="$2"
SERVICE_NAME="madara-$NAME"
CONTAINER_NAME="ds-madara-$NAME"
DATA_DIR="$APPCHAIN_DIR/data/madara-$NAME"

# --- Check for conflicts in both files ---
grep -q "container_name: $CONTAINER_NAME" "$COMPOSE_FILE" && die "$CONTAINER_NAME already exists in compose.yaml"
[ -f "$DYNAMIC_FILE" ] && grep -q "container_name: $CONTAINER_NAME" "$DYNAMIC_FILE" && die "$CONTAINER_NAME already exists in compose.dynamic.yaml"
grep -q "\"$PORT:$PORT\"" "$COMPOSE_FILE" && die "Port $PORT already in use in compose.yaml"
[ -f "$DYNAMIC_FILE" ] && grep -q "\"$PORT:$PORT\"" "$DYNAMIC_FILE" && die "Port $PORT already in use in compose.dynamic.yaml"

# --- Create data directory ---
log "Creating data directory"
mkdir -p "$DATA_DIR"
ok "$DATA_DIR"

# --- Create dynamic file header if it doesn't exist ---
if [ ! -f "$DYNAMIC_FILE" ]; then
  cat > "$DYNAMIC_FILE" << HEADER
services:
HEADER
fi

# --- Append service to dynamic file ---
log "Adding $SERVICE_NAME to compose.dynamic.yaml"
cat >> "$DYNAMIC_FILE" << YAML

  $SERVICE_NAME:
    image: \${MADARA_IMAGE}
    container_name: $CONTAINER_NAME
    depends_on:
      madara:
        condition: service_healthy
    command:
      - "--name"
      - "DroneSwarm-$NAME"
      - "--base-path"
      - "/data/madara-$NAME"
      - "--chain-config-path"
      - "/configs/madara.yaml"
      - "--rpc-port"
      - "$PORT"
      - "--rpc-cors"
      - "*"
      - "--rpc-external"
      - "--full"
      - "--l1-endpoint"
      - "http://besu-validator1:8545"
      - "--gateway-url"
      - "http://madara:8080/gateway"
      - "--strk-per-eth"
      - "1"
      - "--rpc-storage-proof-max-distance"
      - "10000"
    ports:
      - "$PORT:$PORT"
    volumes:
      - ./configs:/configs:ro
      - ./data/madara-$NAME:/data/madara-$NAME
    networks: [appchain]
YAML
ok "Service block added to compose.dynamic.yaml"

log "Done! New full node summary:"
echo "  Name      : $SERVICE_NAME"
echo "  Container : $CONTAINER_NAME"
echo "  RPC port  : $PORT"
echo "  Data dir  : $DATA_DIR"
echo ""
echo "Next steps:"
echo "  Start:  cd $APPCHAIN_DIR && docker compose -f compose.yaml -f compose.dynamic.yaml up -d $SERVICE_NAME"
echo "  Logs:   docker logs -f $CONTAINER_NAME"
echo "  RPC:    http://localhost:$PORT"
echo ""
echo "  On resume (./up.sh --resume), the node will start automatically"
echo "  On fresh start (./up.sh), the node will be removed"
