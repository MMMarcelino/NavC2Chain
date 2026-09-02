# C2 Naval Appchain

Reference implementation accompanying the Master's thesis **"Decentralized
Communication Architecture for C2 Systems Using Blockchain Technology"**
(CINAV / Portuguese Naval Academy).

The thesis models a naval Task Group's command-and-control system as a
two-layer blockchain. The Task Group's ships form a permissioned,
Byzantine-Fault-Tolerant Layer 1 backbone. Drones operate on a Layer 2
validity rollup, where STRK tokens represent operational authorization to
carry out a mission. This repository contains the actual stack used to
build, run, and evaluate that architecture.

## What this is

- A Hyperledger Besu QBFT network (Layer 1) — the Task Group backbone.
- A Madara Starknet appchain (Layer 2) — the drone-swarm rollup.
- A Karnot orchestrator driving an offline proving pipeline: Madara → Cairo
  PIE → Stwo Circle STARK proof → settlement on the Besu L1.
- A custom Node.js gateway (`Layer2/stwo-gateway/`) implementing the
  SHARP-compatible HTTP API in front of a locally-built Stwo prover binary,
  so the entire pipeline runs with no external network calls — a core
  requirement for the naval use case.
- On-chain authorization and workload contracts: an operational
  authorization/delegation registry and a tactical-picture reporting
  contract on Layer 2, and a warfare-authority contract on Layer 1.
- A Node.js load-testing driver (`experiments/driver/`) used to run the
  thesis's experimental campaigns.
- A Grafana/Prometheus/OpenTelemetry observability stack for block
  production, mempool, and proving metrics.

## Repository layout

```
compose.yaml                     Main stack definition
compose.bootstrap-override.yaml  Bootstrap-time overrides
up.sh                             Orchestration script (wipes state + brings up the stack)
configs/                          Madara, bootstrapper, OTEL, Prometheus, alerting configs + TLS fixtures
grafana/                          Dashboards and provisioning
Layer1/besu/                      Besu QBFT genesis, validator keys, config
Layer1/contracts/                 Solidity contracts (warfare-authority)
Layer1/scripts/                   L1-side helper scripts (add_validator.sh)
Layer2/contracts/                 Cairo contracts (tactical_picture, l2_authorisation_registry,
                                   warfare_operations; balance_contract kept for reference)
Layer2/scripts/                   L2-side helper scripts
Layer2/stwo-gateway/              Custom SHARP-compatible Node.js gateway
helper/                           Solidity mock verifier
prover/                           Stwo prover source and build (not vendored — see docs/BUILD.pdf)
experiments/                      Load-testing driver, experimental campaign configs, results and figures
docs/                             Architecture notes, known issues, build instructions (PDF)
archive/                          Superseded configs and scripts kept for reference
```

## Quick start

1. Build the custom images from source — see
   [`docs/BUILD.pdf`](docs/BUILD.pdf). This covers the Madara sequencer,
   bootstrapper-v2, orchestrator, the stwo-gateway, and the standalone Stwo
   prover binary.
2. Copy `.env.example` to `.env` and `orchestrator.env.example` to
   `orchestrator.env`, filling in your own values (deployer private key,
   etc.) — **never commit either file**.
3. Bring up the stack:
   ```bash
   ./up.sh
   ```
4. Deploy a drone account and interact with the Layer 2 contracts using
   `sncast` — see the command sequence in `docs/BUILD.pdf` or the inline
   comments under `Layer2/contracts/`.
5. Open Grafana at `:3001` to watch block production and proving metrics
   live.
6. To reproduce a thesis experimental campaign, see the driver and run
   configs under `experiments/driver/`.

## What's not in this repository

A few things are intentionally excluded — see `.gitignore`:

- `.env`, `orchestrator.env`, and two helper scripts
  (`helper/deploy_verifier.sh`, `Layer1/scripts/fund_l2_accounts.sh`) that
  contain a hardcoded development private key. These are kept in a separate,
  non-public location.
- `data/` and `output/` — live chain state and bootstrapper-generated
  addresses, both fully regenerated on every fresh `./up.sh` run.
- `prover/proving-utils/` — the cloned Stwo prover source and its compiled
  binary. Built separately per `docs/BUILD.pdf`, not vendored here.
- Build artifacts (`cache/`, `out/`, `target/`, `node_modules/`) and raw
  experiment run output (`experiments/logs/`, `experiments/runs/`,
  `experiments/extracts/`).
  
