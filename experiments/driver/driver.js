#!/usr/bin/env node
/**
 * NavC2Chain load driver.
 *
 * Replaces the sncast-based load_test.sh. Key properties:
 *
 *   1. Bounded global concurrency. load_test.sh with INTERVAL=0 spawned an
 *      unbounded number of sncast processes and took the host down. Here the
 *      number of in-flight transactions is capped (--max-in-flight), and the
 *      submit loop blocks on that cap rather than on a sleep.
 *   2. Machine-readable output. Every submission is written to a JSONL file
 *      with submit and accept timestamps, so latency and throughput can be
 *      recomputed after the run instead of being read off a dashboard.
 *   3. No per-transaction estimateFee call. estimateFee validates nonce
 *      against the last SEALED block only, so it incorrectly rejects a
 *      second legitimate pending-nonce transaction from the same account
 *      even though the sequencer's mempool accepts sequential-nonce queued
 *      transactions fine (confirmed empirically 05/08/2026). Each worker
 *      instead takes one real fee estimate at startup and reuses padded
 *      resource bounds for every subsequent submission.
 *
 * Usage:
 *   node driver.js --contract 0x... --rate 2 --duration 3600
 *   node driver.js --contract 0x... --rate 0.5 --phase-file phases.json
 *
 * Ctrl-C stops submission, waits for in-flight transactions, prints a summary.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { RpcProvider, Account, CallData, shortString } from 'starknet';

// --------------------------------------------------------------- arguments --
function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    if (!argv[i].startsWith('--')) continue;
    const key = argv[i].slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) out[key] = true;
    else { out[key] = next; i++; }
  }
  return out;
}

const args = parseArgs(process.argv);

const CFG = {
  rpc: args.rpc || process.env.STARKNET_RPC || 'http://127.0.0.1:9944',
  accountsFile: args.accounts || path.join(os.homedir(),
    '.starknet_accounts', 'starknet_open_zeppelin_accounts.json'),
  profile: args.profile || 'MADARA_DEVNET',
  contract: args.contract || process.env.TACTICAL_PICTURE,
  entrypoint: args.entrypoint || 'report_position',
  // aggregate submissions per second across all accounts
  rate: Number(args.rate ?? 1),
  // hard cap on transactions awaiting acceptance; the real host protection
  maxInFlight: Number(args['max-in-flight'] ?? 8),
  durationSec: args.duration ? Number(args.duration) : null,
  outDir: args.out || './runs',
  label: args.label || 'run',
  // wait for ACCEPTED_ON_L2 before counting a transaction complete
  waitForAccept: args['no-wait'] ? false : true,
  onlyAccounts: args.only ? String(args.only).split(',') : null,
  dryRun: Boolean(args['dry-run']),
  // multiplier applied to the one real fee estimate taken per worker at
  // startup, to keep bounds valid across the whole run without re-estimating
  feePadding: Number(args['fee-padding'] ?? 3),
};

if (!CFG.contract) {
  console.error('error: --contract is required (or set TACTICAL_PICTURE).');
  console.error('       the address changes on every stack rebuild - read it');
  console.error('       from output/madara_addresses.json or sncast output.');
  process.exit(1);
}

// ---------------------------------------------------------------- accounts --
function loadAccounts() {
  const raw = JSON.parse(fs.readFileSync(CFG.accountsFile, 'utf8'));
  const profile = raw[CFG.profile];
  if (!profile) {
    throw new Error(`profile ${CFG.profile} not found in ${CFG.accountsFile}`);
  }
  return Object.entries(profile)
    .filter(([name, a]) => a.deployed !== false)
    .filter(([name]) => !CFG.onlyAccounts || CFG.onlyAccounts.includes(name))
    .map(([name, a]) => ({ name, address: a.address, pk: a.private_key }));
}

// ------------------------------------------------------------------ payload --
// report_position(lat: u64, lon: u64, depth_alt: u64, status: felt252)
//
// All three coordinates are UNSIGNED, so latitude and longitude are stored as
// micro-degrees plus a fixed offset that keeps them positive:
//
//     lat_stored = (lat_degrees + 90)  * 1e6      range 0 .. 180e6
//     lon_stored = (lon_degrees + 180) * 1e6      range 0 .. 360e6
//
// Decoding for analysis is the inverse. The offsets are a property of this
// workload, not of the contract - record them alongside the run.
const LAT_OFFSET = 90_000_000;
const LON_OFFSET = 180_000_000;

// Operating box: roughly the Atlantic approaches to Lisbon.
const BOX = { lat0: 38.4, lat1: 38.9, lon0: -9.6, lon1: -9.1 };

const STATUSES = ['PATROL', 'TRANSIT', 'STATION', 'RTB'];

function encodeStatus(s) {
  return shortString.encodeShortString(s);   // felt252 short string
}

function makePayload(seq) {
  const lat = BOX.lat0 + Math.random() * (BOX.lat1 - BOX.lat0);
  const lon = BOX.lon0 + Math.random() * (BOX.lon1 - BOX.lon0);
  const depthAlt = Math.floor(Math.random() * 200);
  const status = STATUSES[seq % STATUSES.length];
  return [
    Math.round(lat * 1e6) + LAT_OFFSET,
    Math.round(lon * 1e6) + LON_OFFSET,
    depthAlt,
    encodeStatus(status),
  ];
}

function makeCall(seq) {
  return {
    contractAddress: CFG.contract,
    entrypoint: CFG.entrypoint,
    calldata: CallData.compile(makePayload(seq)),
  };
}

// ---------------------------------------------------------- resource bounds --
// One real fee estimate per worker at startup, padded, reused for every
// submission from that worker for the rest of the run. See header comment
// for why estimateFee cannot be called per-transaction.
async function getPaddedBounds(account) {
  const estimate = await account.estimateInvokeFee(makeCall(0));
  const b = estimate.resourceBounds;
  const pad = (v) => v * BigInt(CFG.feePadding);
  return {
    l1_gas: { max_amount: pad(b.l1_gas.max_amount), max_price_per_unit: pad(b.l1_gas.max_price_per_unit || 1n) },
    l2_gas: { max_amount: pad(b.l2_gas.max_amount), max_price_per_unit: pad(b.l2_gas.max_price_per_unit || 1n) },
    l1_data_gas: { max_amount: pad(b.l1_data_gas.max_amount || 0n), max_price_per_unit: pad(b.l1_data_gas.max_price_per_unit || 1n) },
  };
}

// -------------------------------------------------------------------- state --
const stats = {
  submitted: 0, accepted: 0, failed: 0,
  startedAt: 0, latencies: [],
  byAccount: new Map(),
};
let inFlight = 0;
let stopping = false;
let logStream = null;

function log(record) {
  if (logStream) logStream.write(JSON.stringify(record) + '\n');
}

function bump(name, field) {
  if (!stats.byAccount.has(name)) {
    stats.byAccount.set(name, { submitted: 0, accepted: 0, failed: 0 });
  }
  stats.byAccount.get(name)[field]++;
}

// --------------------------------------------------------------- submission --
async function submitOne(worker, seq) {
  const t0 = Date.now();
  inFlight++;
  stats.submitted++;
  bump(worker.name, 'submitted');

  const call = makeCall(seq);

  try {
    const nonce = worker.nonce++;
    const res = await worker.account.execute(call, {
      nonce,
      resourceBounds: worker.resourceBounds,
    });
    const tSubmit = Date.now();

    let acceptedAt = null;
    if (CFG.waitForAccept) {
      await worker.provider.waitForTransaction(res.transaction_hash, {
        retryInterval: 1000,
      });
      acceptedAt = Date.now();
      stats.latencies.push(acceptedAt - t0);
    }

    stats.accepted++;
    bump(worker.name, 'accepted');
    log({
      ts: new Date(t0).toISOString(), account: worker.name, seq,
      tx: res.transaction_hash, nonce,
      submit_ms: tSubmit - t0,
      accept_ms: acceptedAt ? acceptedAt - t0 : null,
      status: 'accepted',
    });
  } catch (err) {
    stats.failed++;
    bump(worker.name, 'failed');
    const msg = String(err && err.message ? err.message : err).slice(0, 500);
    log({
      ts: new Date(t0).toISOString(), account: worker.name, seq,
      status: 'failed', error: msg,
    });
    // A nonce error means the local counter drifted from the chain: resync
    // rather than failing every subsequent submission.
    if (/nonce/i.test(msg)) {
      try {
        worker.nonce = Number(await worker.account.getNonce());
        console.error(`[${worker.name}] nonce resynced to ${worker.nonce}`);
      } catch { /* resync failed; the next attempt will retry */ }
    }
  } finally {
    inFlight--;
  }
}

// ------------------------------------------------------------------ reporting --
function percentile(sorted, p) {
  if (!sorted.length) return null;
  const i = Math.min(sorted.length - 1,
    Math.floor((p / 100) * sorted.length));
  return sorted[i];
}

function summary() {
  const elapsed = (Date.now() - stats.startedAt) / 1000;
  const sorted = [...stats.latencies].sort((a, b) => a - b);
  const mean = sorted.length
    ? sorted.reduce((a, b) => a + b, 0) / sorted.length : null;
  return {
    label: CFG.label,
    elapsed_s: Number(elapsed.toFixed(1)),
    target_rate_tps: CFG.rate,
    submitted: stats.submitted,
    accepted: stats.accepted,
    failed: stats.failed,
    achieved_tps: Number((stats.accepted / elapsed).toFixed(3)),
    latency_ms: sorted.length ? {
      mean: Math.round(mean),
      p50: percentile(sorted, 50),
      p90: percentile(sorted, 90),
      max: sorted[sorted.length - 1],
    } : null,
    per_account: Object.fromEntries(stats.byAccount),
  };
}

function printProgress() {
  const elapsed = (Date.now() - stats.startedAt) / 1000;
  const tps = (stats.accepted / elapsed).toFixed(2);
  process.stdout.write(
    `\r[${Math.round(elapsed)}s] submitted=${stats.submitted} ` +
    `accepted=${stats.accepted} failed=${stats.failed} ` +
    `inflight=${inFlight} tps=${tps}   `);
}

// ----------------------------------------------------------------------- main --
async function main() {
  const provider = new RpcProvider({ nodeUrl: CFG.rpc });
  const chainId = await provider.getChainId();

  const accounts = loadAccounts();
  if (!accounts.length) throw new Error('no deployed accounts found');

  const workers = [];
  for (const a of accounts) {
    const account = new Account({ provider, address: a.address, signer: a.pk });
    const nonce = Number(await account.getNonce());
    console.log(`  ${a.name.padEnd(10)} ${a.address}  nonce=${nonce}  (estimating fee bounds...)`);
    const resourceBounds = await getPaddedBounds(account);
    workers.push({ ...a, account, provider, nonce, resourceBounds });
  }

  fs.mkdirSync(CFG.outDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const base = path.join(CFG.outDir, `${CFG.label}-${stamp}`);
  logStream = fs.createWriteStream(`${base}.jsonl`, { flags: 'a' });

  console.log(`\nchain      ${chainId}`);
  console.log(`rpc        ${CFG.rpc}`);
  console.log(`contract   ${CFG.contract}`);
  console.log(`entrypoint ${CFG.entrypoint}`);
  console.log(`rate       ${CFG.rate} tx/s aggregate`);
  console.log(`in-flight  max ${CFG.maxInFlight}`);
  console.log(`fee bounds padded x${CFG.feePadding} (one estimate per worker, reused)`);
  console.log(`duration   ${CFG.durationSec ? CFG.durationSec + 's' : 'until Ctrl-C'}`);
  console.log(`log        ${base}.jsonl\n`);

  if (CFG.dryRun) {
    console.log('dry run - nothing submitted.');
    return;
  }

  stats.startedAt = Date.now();
  const intervalMs = 1000 / CFG.rate;
  const deadline = CFG.durationSec
    ? stats.startedAt + CFG.durationSec * 1000 : Infinity;

  const progress = setInterval(printProgress, 1000);
  let seq = 0;
  let next = Date.now();

  while (!stopping && Date.now() < deadline) {
    // Backpressure: never exceed maxInFlight. This is what keeps the host
    // alive under an aggressive rate setting.
    if (inFlight >= CFG.maxInFlight) {
      await new Promise(r => setTimeout(r, 20));
      continue;
    }
    const worker = workers[seq % workers.length];
    submitOne(worker, seq).catch(() => {});   // fire and forget; tracked above
    seq++;

    next += intervalMs;
    const wait = next - Date.now();
    if (wait > 0) await new Promise(r => setTimeout(r, wait));
    else next = Date.now();   // behind schedule: do not accumulate debt
  }

  clearInterval(progress);
  process.stdout.write('\n');
  console.log(`draining ${inFlight} in-flight transactions...`);
  while (inFlight > 0) await new Promise(r => setTimeout(r, 200));

  const s = summary();
  fs.writeFileSync(`${base}.summary.json`, JSON.stringify(s, null, 2));
  logStream.end();

  console.log('\n' + JSON.stringify(s, null, 2));
  console.log(`\nsummary written to ${base}.summary.json`);
}

process.on('SIGINT', () => {
  if (stopping) process.exit(1);
  stopping = true;
  console.log('\nstopping - waiting for in-flight transactions (Ctrl-C again to force)');
});

main().catch(err => {
  console.error('\nfatal:', err);
  process.exit(1);
});
