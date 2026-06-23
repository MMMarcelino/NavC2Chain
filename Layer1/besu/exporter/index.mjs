import express from "express";
import { register, Gauge } from "prom-client";

const app = express();

const besuBlockNumber = new Gauge({
  name: "besu_l1_head_block_number",
  help: "Current Besu L1 head block number from eth_blockNumber",
});

const BESU_RPC = process.env.BESU_RPC || "http://besu-validator1:8545";
const SCRAPE_INTERVAL = parseInt(process.env.SCRAPE_INTERVAL || "5000", 10);

async function fetchBlockNumber() {
  try {
    const res = await fetch(BESU_RPC, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "eth_blockNumber", params: [], id: 1 }),
    });
    const data = await res.json();
    const blockNumber = parseInt(data.result, 16);
    besuBlockNumber.set(blockNumber);
  } catch (e) {
    console.error(`[besu-exporter] Failed to fetch block number: ${e.message}`);
  }
}

setInterval(fetchBlockNumber, SCRAPE_INTERVAL);
fetchBlockNumber();

app.get("/metrics", async (req, res) => {
  res.set("Content-Type", register.contentType);
  res.end(await register.metrics());
});

app.get("/is_alive", (req, res) => res.json({ alive: true }));

app.listen(6001, () => console.log(`[besu-exporter] :6001 ready, polling ${BESU_RPC} every ${SCRAPE_INTERVAL}ms`));
