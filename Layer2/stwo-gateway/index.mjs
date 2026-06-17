import express from "express";
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, createWriteStream, readFileSync } from "node:fs";
import { join } from "node:path";

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

const jobs    = new Map();  // key -> { status, batchId, proofPath }
const pending = [];
let flushTimer = null;
let running    = false;
const batchQueue = [];

function flush() {
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  if (pending.length === 0) return;
  const batchId = `batch-${Date.now()}-${pending.length}`;
  const batch   = { batchId, keys: pending.map(p => p.key), piePaths: pending.map(p => p.piePath) };
  pending.length = 0;
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
  for (const k of batch.keys) jobs.set(k, { status: "IN_PROGRESS", batchId: batch.batchId, proofPath });

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
    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
    if (code === 0 && existsSync(proofPath)) {
      console.log(`[gateway] ${batch.batchId} PROCESSED ${elapsed}s (${batch.keys.length} keys)`);
      for (const k of batch.keys) jobs.set(k, { status: "PROCESSED", batchId: batch.batchId, proofPath });
    } else {
      console.error(`[gateway] ${batch.batchId} FAILED exit=${code} ${elapsed}s`);
      for (const k of batch.keys) jobs.set(k, { status: "FAILED", batchId: batch.batchId, proofPath: null });
    }
    running = false;
    drain();
  });
}

// POST /add_job — child PIE job
app.post("/add_job", (req, res) => {
  const key = req.query.cairo_job_key;
  if (!key) return res.status(400).json({ code: "MISSING_JOB_KEY" });

  const { cairo_pie_encoded } = req.body;
  if (!cairo_pie_encoded) return res.status(400).json({ code: "MISSING_PIE" });

  const dir = join(JOBS_DIR, key);
  mkdirSync(dir, { recursive: true });
  const piePath = join(dir, "cairo_pie.zip");
  writeFileSync(piePath, Buffer.from(cairo_pie_encoded, "base64"));

  jobs.set(key, { status: "QUEUED" });
  pending.push({ key, piePath });
  console.log(`[gateway] add_job ${key} pie=${cairo_pie_encoded.length}B (pending=${pending.length}/${BATCH_SIZE})`);

  if (pending.length >= BATCH_SIZE) flush();
  else maybeStartTimer();

  res.json({ code: "JOB_RECEIVED_SUCCESSFULLY" });
});

// POST /add_applicative_job — aggregator job (no proving needed, mock OK)
app.post("/add_applicative_job", (req, res) => {
  const key = req.query.cairo_job_key;
  if (!key) return res.status(400).json({ code: "MISSING_JOB_KEY" });
  console.log(`[gateway] add_applicative_job ${key} (mock: instant PROCESSED)`);
  jobs.set(key, { status: "PROCESSED", proofPath: null });
  res.json({ code: "JOB_RECEIVED_SUCCESSFULLY" });
});

// GET /get_status
app.get("/get_status", (req, res) => {
  const key = req.query.cairo_job_key;
  const job = jobs.get(key);
  if (!job) return res.json({ status: "UNKNOWN", validation_done: false });
  if (job.status === "PROCESSED") return res.json({ status: "PROCESSED", validation_done: true });
  if (job.status === "FAILED")    return res.json({ status: "FAILED",    validation_done: false });
  return res.json({ status: "IN_PROGRESS", validation_done: false });
});

// GET /get_proof
app.get("/get_proof", (req, res) => {
  const key = req.query.cairo_job_key;
  const job = jobs.get(key);
  if (!job || job.status !== "PROCESSED") return res.status(404).json({ error: "proof not ready" });
  if (!job.proofPath || !existsSync(job.proofPath)) {
    // applicative job — return empty proof
    return res.json({});
  }
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

app.listen(6000, () => console.log(`[gateway] :6000 ready BATCH_SIZE=${BATCH_SIZE} FLUSH_MS=${FLUSH_MS}`));
