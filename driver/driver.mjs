#!/usr/bin/env node
// NavC2Chain load driver — invokes report_position on TacticalPicture.
//
//  * MAX_INFLIGHT is a hard ceiling on concurrent unsettled invocations and is
//    independent of RATE. It is the backpressure mechanism: if the node slows
//    down, the driver slows down with it rather than piling up work.
//  * Nonces are fetched once per account and incremented locally.
//  * Fees are estimated once at startup and reused.

import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { RpcProvider, Account, CallData } from 'starknet';

const RPC_URL = process.env.RPC_URL || 'http://localhost:9944';
const CONTRACT = process.env.CONTRACT;
const ACCOUNTS_FILE = process.env.ACCOUNTS_FILE ||
  join(homedir(), '.starknet_accounts', 'starknet_open_zeppelin_accounts.json');
const NETWORK = process.env.NETWORK || 'MADARA_DEVNET';
const RATE = parseFloat(process.env.RATE || '1');
const DURATION = parseInt(process.env.DURATION || '0', 10);
const MAX_INFLIGHT = parseInt(process.env.MAX_INFLIGHT || '8', 10);
const FEE_MULT = parseFloat(process.env.FEE_MULT || '3');
const DRY_RUN = process.env.DRY_RUN === '1';

if (!CONTRACT) {
  console.error('CONTRACT is required (TacticalPicture address)');
  process.exit(1);
}

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

const raw = JSON.parse(readFileSync(ACCOUNTS_FILE, 'utf-8'));
const net = raw[NETWORK];
if (!net) {
  console.error(`network ${NETWORK} not found; available: ${Object.keys(raw).join(', ')}`);
  process.exit(1);
}

const provider = new RpcProvider({ nodeUrl: RPC_URL });

const units = Object.entries(net)
  .filter(([, a]) => a.deployed)
  .map(([name, a]) => ({
    name,
    address: a.address,
    account: new Account({ provider, address: a.address, signer: a.private_key, cairoVersion: '1' }),
    nonce: 0n,
    sent: 0,
    failed: 0,
  }));

if (units.length === 0) {
  console.error('no deployed accounts found');
  process.exit(1);
}

const STATUS = { PTDrone: 1n, ESDrone: 2n, FRDrone: 3n, UKDrone: 4n };
const base = { lat: 38700000n, lon: -9150000n };
let tick = 0n;

function buildCall(unit, i) {
  const drift = BigInt(i) * 7n + tick;
  const lat = base.lat + (drift % 20000n);
  const lon = 180000000n + base.lon + (drift % 15000n);
  const depth_alt = 100n + (drift % 900n);
  const status = STATUS[unit.name] ?? 0n;
  return {
    contractAddress: CONTRACT,
    entrypoint: 'report_position',
    calldata: CallData.compile([
      lat.toString(), lon.toString(), depth_alt.toString(), status.toString(),
    ]),
  };
}

let resourceBounds = null;

function scaleBounds(rb, mult) {
  if (!rb) return null;
  const out = {};
  for (const [k, v] of Object.entries(rb)) {
    if (!v || typeof v !== 'object') continue;
    const amt = BigInt(v.max_amount ?? 0);
    const price = BigInt(v.max_price_per_unit ?? 0);
    out[k] = { ...v,
      max_amount: amt * BigInt(Math.ceil(mult)),
      max_price_per_unit: price * BigInt(Math.ceil(mult)),
    };
  }
  return Object.keys(out).length ? out : null;
}

async function prepare() {
  log(`rpc=${RPC_URL}`);
  log(`contract=${CONTRACT}`);
  log(`units=${units.map(u => u.name).join(',')}`);

  const chainId = await provider.getChainId();
  const block = await provider.getBlockLatestAccepted();
  log(`chain=${chainId} head=${block.block_number}`);

  for (const u of units) {
    u.nonce = BigInt(await u.account.getNonce('latest'));
    log(`  ${u.name} nonce=${u.nonce}`);
  }

  try {
    const est = await units[0].account.estimateInvokeFee(buildCall(units[0], 0), { blockIdentifier: 'latest', nonce: '0x' + units[0].nonce.toString(16) });
    resourceBounds = scaleBounds(est.resourceBounds, FEE_MULT);
    log(resourceBounds
      ? `fee estimated once, bounds scaled x${FEE_MULT}`
      : 'estimate returned no resourceBounds — will estimate per transaction');
  } catch (e) {
    log(`fee estimation failed (${e.message}) — will estimate per transaction`);
  }
}

let inflight = 0;
let sent = 0, ok = 0, failed = 0, throttled = 0;
let stopping = false;

async function send(unit, i) {
  const call = buildCall(unit, i);
  const nonce = unit.nonce++;
  inflight++;
  try {
    const details = { nonce: '0x' + nonce.toString(16) };
    if (resourceBounds) details.resourceBounds = resourceBounds;
    await unit.account.execute(call, details);
    ok++; unit.sent++;
  } catch (e) {
    failed++; unit.failed++;
    if (failed <= 5 || failed % 50 === 0) log(`  ${unit.name} tx failed: ${e.message.slice(0, 140)}`);
    try { unit.nonce = BigInt(await unit.account.getNonce('latest')); } catch { /* retry next cycle */ }
  } finally {
    inflight--;
  }
}

async function run() {
  const started = Date.now();
  const interval = 1000 / RATE;
  let i = 0;
  let next = Date.now();

  while (!stopping) {
    if (DURATION > 0 && (Date.now() - started) / 1000 >= DURATION) break;

    if (inflight >= MAX_INFLIGHT) {
      throttled++;
      await new Promise(r => setTimeout(r, 25));
      continue;
    }

    const unit = units[i % units.length];
    if (i % units.length === 0) tick += 1n;
    send(unit, i);
    sent++; i++;

    next += interval;
    const wait = next - Date.now();
    if (wait > 0) await new Promise(r => setTimeout(r, wait));
    else next = Date.now();
  }

  log('draining...');
  while (inflight > 0) await new Promise(r => setTimeout(r, 100));
}

const t0 = Date.now();
const stats = setInterval(() => {
  const el = (Date.now() - t0) / 1000;
  log(`sent=${sent} ok=${ok} failed=${failed} inflight=${inflight} ` +
      `throttled=${throttled} rate=${(ok / el).toFixed(2)}/s elapsed=${el.toFixed(0)}s`);
}, 10000);

function summary() {
  const el = (Date.now() - t0) / 1000;
  console.log('\n--- summary ---');
  console.log(`duration      ${el.toFixed(1)} s`);
  console.log(`requested     ${RATE} tx/s`);
  console.log(`accepted      ${ok}  (${(ok / el).toFixed(3)} tx/s)`);
  console.log(`failed        ${failed}`);
  console.log(`throttle hits ${throttled}   (max inflight ${MAX_INFLIGHT})`);
  for (const u of units) console.log(`  ${u.name.padEnd(10)} ok=${u.sent} failed=${u.failed}`);
}

process.on('SIGINT', () => { log('SIGINT — stopping'); stopping = true; });

await prepare();

if (DRY_RUN) {
  log('DRY RUN — no transactions will be sent');
  for (const [i, u] of units.entries()) {
    console.log(`  ${u.name}`, JSON.stringify(buildCall(u, i)));
  }
  clearInterval(stats);
  process.exit(0);
}

await run();
clearInterval(stats);
summary();
process.exit(0);
