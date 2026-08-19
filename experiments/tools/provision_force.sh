#!/usr/bin/env bash
# Provision the scenario force on Layer 2.
#
#   ./provision-force.sh create    create all accounts, print funding table
#   ./provision-force.sh deploy    deploy them (after funding)
#   ./provision-force.sh status    show which are deployed
#
# Twelve accounts: three warfare commanders and nine vehicles, three per
# warfare domain. COMSNMG1 is assumed to be an existing account (PTDrone by
# default) - override with COMMAND_ACCOUNT.
set -uo pipefail

URL="${STARKNET_RPC:-http://localhost:9944}"
COMMAND_ACCOUNT="${COMMAND_ACCOUNT:-PTDrone}"

# name          domain   note
FORCE=(
  "AAWC|AAW|France - FS Chevalier Paul - anti-air warfare commander"
  "ASWC|ASW|United Kingdom - HMS Portland - anti-submarine warfare commander"
  "ASUWC|ASUW|Spain - ESPS Alvaro de Bazan - anti-surface warfare commander"
  "AAW01|AAW|UAV - air picture"
  "AAW02|AAW|UAV - air picture"
  "AAW03|AAW|UAV - air picture"
  "ASW01|ASW|UUV - subsurface"
  "ASW02|ASW|UUV - subsurface"
  "ASW03|ASW|UUV - subsurface"
  "ASUW01|ASUW|USV - surface"
  "ASUW02|ASUW|USV - surface"
  "ASUW03|ASUW|USV - surface"
)

ACCT_FILE="$HOME/.starknet_accounts/starknet_open_zeppelin_accounts.json"

addr_of() {
  python3 -c "
import json,sys
try:
    a=json.load(open('$ACCT_FILE'))['MADARA_DEVNET'].get('$1')
    print(a['address'] if a else '')
except Exception:
    print('')"
}

deployed_of() {
  python3 -c "
import json
try:
    a=json.load(open('$ACCT_FILE'))['MADARA_DEVNET'].get('$1')
    print('yes' if a and a.get('deployed') else 'no')
except Exception:
    print('no')"
}

case "${1:-status}" in

create)
  echo "creating ${#FORCE[@]} accounts against $URL"
  for entry in "${FORCE[@]}"; do
    IFS='|' read -r name domain note <<< "$entry"
    if [ -n "$(addr_of "$name")" ]; then
      echo "  $name already exists, skipping"
      continue
    fi
    echo "  creating $name ($note)"
    sncast account create --name "$name" --url "$URL" --type oz >/dev/null 2>&1 \
      || echo "    WARNING: create failed for $name"
  done
  echo
  echo "=== fund these addresses, then run: $0 deploy ==="
  printf '%-8s %-6s %s\n' NAME DOMAIN ADDRESS
  for entry in "${FORCE[@]}"; do
    IFS='|' read -r name domain note <<< "$entry"
    printf '%-8s %-6s %s\n' "$name" "$domain" "$(addr_of "$name")"
  done
  ;;

deploy)
  echo "deploying accounts that are funded but not yet on chain"
  for entry in "${FORCE[@]}"; do
    IFS='|' read -r name domain note <<< "$entry"
    if [ "$(deployed_of "$name")" = "yes" ]; then
      echo "  $name already deployed"
      continue
    fi
    echo "  deploying $name"
    sncast account deploy --name "$name" --url "$URL" 2>&1 | tail -2 | sed 's/^/    /'
  done
  ;;

delegate)
  # Requires REGISTRY to be set to the deployed registry address.
  : "${REGISTRY:?set REGISTRY to the AuthorisationRegistry address}"
  hexof() { python3 -c "
import sys
s='$1'
print('0x'+''.join(format(ord(c),'02x') for c in s))"; }

  echo "Command ($COMMAND_ACCOUNT) appointing warfare commanders"
  for entry in "${FORCE[@]:0:3}"; do
    IFS='|' read -r name domain note <<< "$entry"
    d=$(python3 -c "print('0x'+''.join(format(ord(c),'02x') for c in '$domain'))")
    echo "  appoint $name domain=$domain ($d)"
    sncast --account "$COMMAND_ACCOUNT" invoke --url "$URL" \
      --contract-address "$REGISTRY" --function appoint_commander \
      --calldata "$(addr_of "$name")" "$d" 2>&1 | tail -1 | sed 's/^/    /'
  done

  echo
  echo "warfare commanders authorising their vehicles"
  for entry in "${FORCE[@]:3}"; do
    IFS='|' read -r name domain note <<< "$entry"
    case "$domain" in
      AAW)  cmd=AAWC  ;;
      ASW)  cmd=ASWC  ;;
      ASUW) cmd=ASUWC ;;
    esac
    role=$(python3 -c "print('0x'+''.join(format(ord(c),'02x') for c in 'ISR'))")
    echo "  $cmd authorises $name"
    sncast --account "$cmd" invoke --url "$URL" \
      --contract-address "$REGISTRY" --function authorise \
      --calldata "$(addr_of "$name")" "$role" 2>&1 | tail -1 | sed 's/^/    /'
  done
  ;;

status)
  printf '%-8s %-6s %-9s %s\n' NAME DOMAIN DEPLOYED ADDRESS
  for entry in "${FORCE[@]}"; do
    IFS='|' read -r name domain note <<< "$entry"
    printf '%-8s %-6s %-9s %s\n' "$name" "$domain" "$(deployed_of "$name")" \
      "$(addr_of "$name")"
  done
  ;;

*)
  echo "usage: $0 {create|deploy|delegate|status}"
  exit 1
  ;;
esac
