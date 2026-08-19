#!/usr/bin/env node
/**
 * Diagnostic: does the sequencer's add_invoke_transaction path accept
 * several sequential-nonce transactions from ONE account without waiting
 * for each to seal, as long as we supply resourceBounds directly and skip
 * the estimateFee RPC call (which only sees the last SEALED nonce)?
 *
 * If yes: the real fix is bypassing estimateFee in driver.js, no new
 * accounts needed. If no: the sequencer's mempool has the same "latest
 * sealed nonce only" limitation, and we fall back to Option 2 (more
 * accounts, lower ladder ceiling).
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { RpcProvider, Account, CallData, shortString } from 'starknet';

const CONTRACT = process.argv[2];
const ACCOUNT_NAME = process.argv[3] || 'PTDrone';
const N = 5; // how many rapid-fire sequential-nonce txs to attempt

if (!CONTRACT) {
  console.error('usage: node nonce_bypass_test.js <contract_address> [account_name]');
  process.exit(1);
}

async function main() {
  const provider = new RpcProvider({ nodeUrl: 'http://127.0.0.1:9944' });

  const accountsFile = path.join(os.homedir(),
    '.starknet_accounts', 'starknet_open_zeppelin_accounts.json');
  const raw = JSON.parse(fs.readFileSync(accountsFile, 'utf8'));
  const a = raw['MADARA_DEVNET'][ACCOUNT_NAME];
  const account = new Account({ provider, address: a.address, signer: a.private_key });

  const startNonce = Number(await account.getNonce());
  console.log(`account ${ACCOUNT_NAME} starting nonce = ${startNonce}`);

  // One real estimateFee call, to get valid resourceBounds we can reuse
  // (with margin) for every subsequent tx so we never call estimateFee again.
  const sampleCall = {
    contractAddress: CONTRACT,
    entrypoint: 'report_position',
    calldata: CallData.compile([90_000_000, 180_000_000, 0, shortString.encodeShortString('PATROL')]),
  };
  const feeEstimate = await account.estimateInvokeFee(sampleCall, { nonce: startNonce });
  console.log('sample fee estimate:', feeEstimate);

  // Pull resource bounds out of the estimate and pad generously so every
  // subsequent tx is guaranteed to pass, since we won't re-estimate.
  const bounds = feeEstimate.resourceBounds;
  const padded = {
    l1_gas: {
      max_amount: bounds.l1_gas.max_amount * 3n,
      max_price_per_unit: bounds.l1_gas.max_price_per_unit * 3n,
    },
    l2_gas: {
      max_amount: bounds.l2_gas.max_amount * 3n,
      max_price_per_unit: bounds.l2_gas.max_price_per_unit * 3n,
    },
    l1_data_gas: {
      max_amount: bounds.l1_data_gas.max_amount * 3n,
      max_price_per_unit: (bounds.l1_data_gas.max_price_per_unit || 1n) * 3n,
    },
  };

  console.log(`\nfiring ${N} sequential-nonce txs, back to back, no waiting...`);
  const hashes = [];
  const t0 = Date.now();
  for (let i = 0; i < N; i++) {
    const nonce = startNonce + i;
    try {
      const res = await account.execute(sampleCall, {
        nonce,
        resourceBounds: padded,
        skipValidate: false,
      });
      console.log(`  [${i}] nonce=${nonce} submitted -> ${res.transaction_hash}`);
      hashes.push(res.transaction_hash);
    } catch (err) {
      console.log(`  [${i}] nonce=${nonce} FAILED -> ${String(err.message || err).slice(0, 200)}`);
    }
  }
  console.log(`\nall ${N} submissions issued in ${Date.now() - t0}ms (no per-tx wait)`);

  console.log('\nwaiting up to 30s, then checking final status of each...');
  await new Promise(r => setTimeout(r, 30000));

  for (const h of hashes) {
    try {
      const receipt = await provider.getTransactionReceipt(h);
      console.log(`  ${h.slice(0, 12)}... -> ${receipt.execution_status || receipt.status}`);
    } catch (err) {
      console.log(`  ${h.slice(0, 12)}... -> NOT FOUND (${String(err.message || err).slice(0, 100)})`);
    }
  }

  const finalNonce = Number(await account.getNonce());
  console.log(`\nfinal sealed nonce = ${finalNonce} (started at ${startNonce}, attempted ${N})`);
  console.log(finalNonce === startNonce + N
    ? '=> ALL LANDED. Sequencer accepts queued pending-nonce txs. Option 3 viable.'
    : `=> only ${finalNonce - startNonce}/${N} landed. Same ceiling as before, fall back to Option 2.`);
}

main().catch(err => { console.error('fatal:', err); process.exit(1); });
