import express from "express";
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, createWriteStream, readFileSync, statSync } from "node:fs";
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

      console.log(`[gateway] ${batch.batchId} PROCESSED ${elapsedStr}s (${batch.keys.length} keys)`);
      for (const k of batch.keys) jobs.set(k, { status: "PROCESSED", batchId: batch.batchId, proofPath });
    } else {
      proofBatchesFailed.inc();

      console.error(`[gateway] ${batch.batchId} FAILED exit=${code} ${elapsedStr}s`);
      for (const k of batch.keys) jobs.set(k, { status: "FAILED", batchId: batch.batchId, proofPath: null });
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

  jobs.set(key, { status: "QUEUED" });
  pending.push({ key, piePath });

  jobsTotal.inc();
  jobsQueued.set(pending.length);

  console.log(`[gateway] add_job ${key} pie=${cairo_pie_encoded.length}B (pending=${pending.length}/${BATCH_SIZE})`);

  if (pending.length >= BATCH_SIZE) flush();
  else maybeStartTimer();

  res.json({ code: "JOB_RECEIVED_SUCCESSFULLY" });
});

// POST /add_applicative_job
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

app.listen(6000, () => console.log(`[gateway] :6000 ready BATCH_SIZE=${BATCH_SIZE} FLUSH_MS=${FLUSH_MS}`));
