import express from "express";
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, createWriteStream, readFileSync, statSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { register, Gauge, Counter, Histogram } from "prom-client";

// ── Prometheus metrics ────────────────────────────────────────────────────────
const proofGenerationTime = new Gauge({
  name: "proof_generation_seconds",
  help: "Wall-clock time for the last Stwo proof generation (seconds)",
});

const proofSizeBytes = new Gauge({
  name: "proof_size_bytes",
  help: "Size of the last generated proof JSON file (bytes)",
});

const proofBatchesTotal = new Counter({
  name: "proof_batches_total",
  help: "Total number of proof batches attempted",
});

const proofBatchesSucceeded = new Counter({
  name: "proof_batches_succeeded_total",
  help: "Total number of proof batches that succeeded",
});

const proofBatchesFailed = new Counter({
  name: "proof_batches_failed_total",
  help: "Total number of proof batches that failed",
});

const proofBatchSize = new Gauge({
  name: "proof_batch_size_transactions",
  help: "Number of PIEs (transactions) in the last proof batch",
});

const proofGenerationHistogram = new Histogram({
  name: "proof_generation_seconds_histogram",
  help: "Distribution of proof generation times (seconds)",
  buckets: [5, 10, 15, 20, 25, 30, 40, 50, 60, 90, 120],
});

const jobsQueued = new Gauge({
  name: "gateway_jobs_pending",
  help: "Number of jobs currently waiting to be batched",
});

const jobsInFlight = new Gauge({
  name: "gateway_jobs_in_flight",
  help: "Number of jobs currently being proved (0 or batch size)",
});

const jobsTotal = new Counter({
  name: "gateway_jobs_received_total",
  help: "Total number of jobs received via /add_job",
});

// ── Storage metrics ───────────────────────────────────────────────────────────
const storageJobsDirBytes = new Gauge({
  name: "gateway_storage_pies_bytes",
  help: "Total disk space used by all Cairo PIE zip files in /tmp/jobs (bytes)",
});

const storageProofsDirBytes = new Gauge({
  name: "gateway_storage_proofs_bytes",
  help: "Total disk space used by all proof JSON files in /tmp/batches (bytes)",
});

const storageLogsDirBytes = new Gauge({
  name: "gateway_storage_logs_bytes",
  help: "Total disk space used by all run.log files in /tmp/batches (bytes)",
});

const storageProgramInputBytes = new Gauge({
  name: "gateway_storage_program_inputs_bytes",
  help: "Total disk space used by all program_input.json files in /tmp/batches (bytes)",
});

const storageTotalBytes = new Gauge({
  name: "gateway_storage_total_bytes",
  help: "Total disk space used by all gateway artifacts combined (bytes)",
});
// ─────────────────────────────────────────────────────────────────────────────

const app = express();
app.use(express.json({ limit: "200mb" }));

const JOBS_DIR    = process.env.JOBS_DIR    || "/tmp/jobs";
const BATCHES_DIR = process.env.BATCHES_DIR || "/tmp/batches";
const BOOTLOADER  = process.env.BOOTLOADER  || "/opt/simple_bootloader_compiled.json";
const PROVER_BIN  = process.env.PROVER_BIN  || "/usr/local/bin/stwo-run-and-prove";
const BATCH_SIZE  = parseInt(process.env.BATCH_SIZE || "5", 10);
const FLUSH_MS    = parseInt(process.env.FLUSH_MS   || "30000", 10);

mkdirSync(JOBS_DIR,    { recursive: true });
mkdirSync(BATCHES_DIR, { recursive: true });

const jobs    = new Map();
const pending = [];
let flushTimer = null;
let running    = false;
const batchQueue = [];

// ── Durable job state ─────────────────────────────────────────────────────────
const jobsRequeued = new Counter({
  name: "gateway_jobs_requeued_total",
  help: "Jobs re-queued for proving after a gateway restart",
});

function statePath(key) { return join(JOBS_DIR, key, "state.json"); }

function setJob(key, val) {
  jobs.set(key, val);
  try {
    mkdirSync(join(JOBS_DIR, key), { recursive: true });
    writeFileSync(statePath(key), JSON.stringify(val));
  } catch (e) {
    console.error(`[gateway] state write failed ${key}: ${e.message}`);
  }
}

function getJob(key) {
  if (!key) return undefined;
  if (jobs.has(key)) return jobs.get(key);
  try {
    const v = JSON.parse(readFileSync(statePath(key), "utf-8"));
    jobs.set(key, v);
    return v;
  } catch (_) { return undefined; }
}

function rehydrate() {
  let restored = 0, requeued = 0;
  let entries = [];
  try { entries = readdirSync(JOBS_DIR, { withFileTypes: true }); } catch (_) { return; }

  for (const e of entries) {
    if (!e.isDirectory()) continue;
    const key = e.name;
    let st = null;
    try { st = JSON.parse(readFileSync(statePath(key), "utf-8")); } catch (_) {}

    if (st && st.status === "PROCESSED" && (!st.proofPath || existsSync(st.proofPath))) {
      jobs.set(key, st);
      restored++;
      continue;
    }

    const piePath = join(JOBS_DIR, key, "cairo_pie.zip");
    if (existsSync(piePath)) {
      jobs.set(key, { status: "QUEUED" });
      pending.push({ key, piePath });
      jobsRequeued.inc();
      requeued++;
    }
  }

  jobsQueued.set(pending.length);
  console.log(`[gateway] rehydrate: ${restored} restored, ${requeued} requeued`);
  if (pending.length >= BATCH_SIZE) flush();
  else maybeStartTimer();
}

// ── Directory size scanner ────────────────────────────────────────────────────
function dirSize(dirPath) {
  let total = 0;
  try {
    for (const entry of readdirSync(dirPath, { withFileTypes: true })) {
      const full = join(dirPath, entry.name);
      if (entry.isDirectory()) {
        total += dirSize(full);
      } else {
        try { total += statSync(full).size; } catch (_) {}
      }
    }
  } catch (_) {}
  return total;
}

function scanStorageByType(baseDir) {
  let pies = 0, proofs = 0, logs = 0, inputs = 0;
  try {
    // /tmp/jobs/<key>/cairo_pie.zip
    for (const job of readdirSync(JOBS_DIR, { withFileTypes: true })) {
      if (!job.isDirectory()) continue;
      const piePath = join(JOBS_DIR, job.name, "cairo_pie.zip");
      try { pies += statSync(piePath).size; } catch (_) {}
    }
    // /tmp/batches/<batchId>/{proof.json, run.log, program_input.json}
    for (const batch of readdirSync(BATCHES_DIR, { withFileTypes: true })) {
      if (!batch.isDirectory()) continue;
      const batchPath = join(BATCHES_DIR, batch.name);
      const proofPath = join(batchPath, "proof.json");
      const logPath   = join(batchPath, "run.log");
      const inputPath = join(batchPath, "program_input.json");
      try { proofs += statSync(proofPath).size; } catch (_) {}
      try { logs   += statSync(logPath).size;   } catch (_) {}
      try { inputs += statSync(inputPath).size; } catch (_) {}
    }
  } catch (_) {}
  return { pies, proofs, logs, inputs };
}

function updateStorageMetrics() {
  const { pies, proofs, logs, inputs } = scanStorageByType();
  storageJobsDirBytes.set(pies);
  storageProofsDirBytes.set(proofs);
  storageLogsDirBytes.set(logs);
  storageProgramInputBytes.set(inputs);
  storageTotalBytes.set(pies + proofs + logs + inputs);
}
// ─────────────────────────────────────────────────────────────────────────────

function flush() {
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  if (pending.length === 0) return;
  const batchId = `batch-${Date.now()}-${pending.length}`;
  const batch   = { batchId, keys: pending.map(p => p.key), piePaths: pending.map(p => p.piePath) };
  pending.length = 0;
  jobsQueued.set(0);
  batchQueue.push(batch);
  console.log(`[gateway] BATCH ${batchId} sealed (${batch.keys.length} PIEs)`);
  if (!running) drain();
}

function maybeStartTimer() {
  if (flushTimer || pending.length === 0) return;
  flushTimer = setTimeout(flush, FLUSH_MS);
}

function drain() {
  if (running) return;
  const batch = batchQueue.shift();
  if (!batch) return;
  running = true;

  const dir              = join(BATCHES_DIR, batch.batchId);
  mkdirSync(dir, { recursive: true });
  const programInputPath = join(dir, "program_input.json");
  const proofPath        = join(dir, "proof.json");

  writeFileSync(programInputPath, JSON.stringify({
    tasks: batch.piePaths.map(p => ({
      type: "CairoPiePath",
      path: p,
      program_hash_function: "pedersen",
    })),
    single_page: true,
  }, null, 2));

  console.log(`[gateway] PROVING ${batch.batchId}`);
  const startedAt = Date.now();

  proofBatchesTotal.inc();
  proofBatchSize.set(batch.keys.length);
  jobsInFlight.set(batch.keys.length);

  for (const k of batch.keys) setJob(k, { status: "IN_PROGRESS", batchId: batch.batchId, proofPath });

  const child = spawn(PROVER_BIN, [
    "--program",       BOOTLOADER,
    "--program_input", programInputPath,
    "--proof_path",    proofPath,
    "--proof-format",  "json",
    "--verify",
  ], { stdio: ["ignore", "pipe", "pipe"] });

  const log = createWriteStream(join(dir, "run.log"));
  child.stdout.pipe(log);
  child.stderr.pipe(log);

  child.on("exit", (code) => {
    const elapsed = (Date.now() - startedAt) / 1000;
    const elapsedStr = elapsed.toFixed(1);

    jobsInFlight.set(0);

    if (code === 0 && existsSync(proofPath)) {
      proofGenerationTime.set(elapsed);
      proofGenerationHistogram.observe(elapsed);
      proofBatchesSucceeded.inc();
      try {
        const size = statSync(proofPath).size;
        proofSizeBytes.set(size);
      } catch (_) {}

      // update storage breakdown after each successful proof
      updateStorageMetrics();

      console.log(`[gateway] ${batch.batchId} PROCESSED ${elapsedStr}s (${batch.keys.length} keys)`);
      for (const k of batch.keys) setJob(k, { status: "PROCESSED", batchId: batch.batchId, proofPath });
    } else {
      proofBatchesFailed.inc();
      console.error(`[gateway] ${batch.batchId} FAILED exit=${code} ${elapsedStr}s`);
      for (const k of batch.keys) setJob(k, { status: "FAILED", batchId: batch.batchId, proofPath: null });
    }
    running = false;
    drain();
  });
}

// POST /add_job
app.post("/add_job", (req, res) => {
  const key = req.query.cairo_job_key;
  if (!key) return res.status(400).json({ code: "MISSING_JOB_KEY" });

  const { cairo_pie_encoded } = req.body;
  if (!cairo_pie_encoded) return res.status(400).json({ code: "MISSING_PIE" });

  const dir = join(JOBS_DIR, key);
  mkdirSync(dir, { recursive: true });
  const piePath = join(dir, "cairo_pie.zip");
  writeFileSync(piePath, Buffer.from(cairo_pie_encoded, "base64"));

  setJob(key, { status: "QUEUED" });
  pending.push({ key, piePath });

  jobsTotal.inc();
  jobsQueued.set(pending.length);

  console.log(`[gateway] add_job ${key} pie=${cairo_pie_encoded.length}B (pending=${pending.length}/${BATCH_SIZE})`);

  if (pending.length >= BATCH_SIZE) flush();
  else maybeStartTimer();

  res.json({ code: "JOB_RECEIVED_SUCCESSFULLY" });
});

// POST /add_applicative_job -- prove aggregated PIE with Stwo (same as add_job)
app.post("/add_applicative_job", (req, res) => {
  const key = req.query.cairo_job_key;
  if (!key) return res.status(400).json({ code: "MISSING_JOB_KEY" });

  const { cairo_pie_encoded, children_cairo_job_keys } = req.body;

  if (!cairo_pie_encoded) {
    console.log(`[gateway] add_applicative_job ${key} (no PIE -- mock: instant PROCESSED)`);
    setJob(key, { status: "PROCESSED", proofPath: null });
    return res.json({ code: "JOB_RECEIVED_SUCCESSFULLY" });
  }

  const dir = join(JOBS_DIR, key);
  mkdirSync(dir, { recursive: true });
  const piePath = join(dir, "cairo_pie.zip");
  writeFileSync(piePath, Buffer.from(cairo_pie_encoded, "base64"));

  setJob(key, { status: "QUEUED" });
  pending.push({ key, piePath });

  jobsTotal.inc();
  jobsQueued.set(pending.length);

  console.log(`[gateway] add_applicative_job ${key} pie=${cairo_pie_encoded.length}B children=${(children_cairo_job_keys||[]).length} (pending=${pending.length}/${BATCH_SIZE})`);

  if (pending.length >= BATCH_SIZE) flush();
  else maybeStartTimer();

  res.json({ code: "JOB_RECEIVED_SUCCESSFULLY" });
});

// GET /get_status
app.get("/get_status", (req, res) => {
  const key = req.query.cairo_job_key;
  const job = getJob(key);
  if (!job) return res.json({ status: "UNKNOWN", validation_done: false });
  if (job.status === "PROCESSED") return res.json({ status: "PROCESSED", validation_done: true });
  if (job.status === "FAILED")    return res.json({ status: "FAILED",    validation_done: false });
  return res.json({ status: "IN_PROGRESS", validation_done: false });
});

// GET /get_proof
app.get("/get_proof", (req, res) => {
  const key = req.query.cairo_job_key;
  const job = getJob(key);
  if (!job || job.status !== "PROCESSED") return res.status(404).json({ error: "proof not ready" });
  if (!job.proofPath || !existsSync(job.proofPath)) return res.json({});
  try {
    const proof = readFileSync(job.proofPath, "utf-8");
    res.setHeader("Content-Type", "application/json");
    res.send(proof);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /is_alive
app.get("/is_alive", (req, res) => res.json({ alive: true }));

// GET /metrics
app.get("/metrics", async (req, res) => {
  res.set("Content-Type", register.contentType);
  res.end(await register.metrics());
});

app.listen(6000, () => {
  // scan existing artifacts on startup so metrics are non-zero immediately
  updateStorageMetrics();
  rehydrate();
  console.log(`[gateway] :6000 ready BATCH_SIZE=${BATCH_SIZE} FLUSH_MS=${FLUSH_MS}`);
});
