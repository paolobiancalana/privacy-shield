#!/usr/bin/env node
/**
 * SDK Build Verification Script
 * Verifies bundle integrity, exports, minification, and live API calls.
 *
 * Usage:
 *   node scripts/verify-build.mjs [--api-key <key>] [--org-id <uuid>]
 *
 * Env vars (alternative to flags):
 *   PS_API_KEY    - API key for functional tests
 *   PS_ORG_ID     - Organization UUID
 *   PS_BASE_URL   - Base URL (default: https://api.privacyshield.pro)
 */

import { readFileSync, statSync } from "fs";
import { createRequire } from "module";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

// ─── CLI / env config ───────────────────────────────────────────────────────

const args = process.argv.slice(2);
function getArg(flag) {
  const i = args.indexOf(flag);
  return i !== -1 ? args[i + 1] : undefined;
}

const API_KEY = getArg("--api-key") ?? process.env.PS_API_KEY;
const ORG_ID = getArg("--org-id") ?? process.env.PS_ORG_ID;
const BASE_URL = getArg("--base-url") ?? process.env.PS_BASE_URL ?? "https://api.privacyshield.pro";

// ─── Helpers ────────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function ok(label) {
  console.log(`  ✓  ${label}`);
  passed++;
}

function fail(label, reason) {
  console.error(`  ✗  ${label}`);
  if (reason) console.error(`     → ${reason}`);
  failed++;
}

function section(title) {
  console.log(`\n── ${title} ${"─".repeat(Math.max(0, 60 - title.length - 4))}`);
}

// ─── 1. BUNDLE SIZE CHECK ───────────────────────────────────────────────────

section("1. Bundle Size & Minification");

const ESM_PATH = path.join(ROOT, "dist/index.js");
const CJS_PATH = path.join(ROOT, "dist/index.cjs");
const DTS_PATH = path.join(ROOT, "dist/index.d.ts");

for (const [label, filePath] of [
  ["dist/index.js (ESM)", ESM_PATH],
  ["dist/index.cjs (CJS)", CJS_PATH],
  ["dist/index.d.ts", DTS_PATH],
]) {
  try {
    const size = statSync(filePath).size;
    ok(`${label} exists (${(size / 1024).toFixed(1)} KB)`);
  } catch {
    fail(`${label} exists`, "file not found");
  }
}

// Minification check: ESM and CJS bundles should each fit on ≤5 logical lines
// (minified output is typically 1–2 very long lines)
for (const [label, filePath] of [
  ["ESM bundle is minified", ESM_PATH],
  ["CJS bundle is minified", CJS_PATH],
]) {
  try {
    const content = readFileSync(filePath, "utf8");
    const lines = content.split("\n").filter((l) => l.trim().length > 0);
    if (lines.length <= 5) {
      ok(`${label} (${lines.length} non-empty lines)`);
    } else {
      fail(label, `${lines.length} non-empty lines — expected ≤5 for a minified bundle`);
    }
  } catch (e) {
    fail(label, String(e));
  }
}

// No source maps should be shipped
for (const mapFile of ["dist/index.js.map", "dist/index.cjs.map"]) {
  const mapPath = path.join(ROOT, mapFile);
  try {
    statSync(mapPath);
    fail(`No ${mapFile} in dist`, "source map file found — remove it before publishing");
  } catch {
    ok(`No ${mapFile} shipped`);
  }
}

// ─── 2. EXPORT CHECK (ESM) ──────────────────────────────────────────────────

section("2. Exports — ESM (import)");

let PrivacyShield, PrivacyShieldAdmin, PrivacyShieldApiError;

try {
  const mod = await import(ESM_PATH);
  PrivacyShield = mod.PrivacyShield;
  PrivacyShieldAdmin = mod.PrivacyShieldAdmin;
  PrivacyShieldApiError = mod.PrivacyShieldApiError;

  ok("PrivacyShield exported");
  ok("PrivacyShieldAdmin exported");
  ok("PrivacyShieldApiError exported");

  if (typeof PrivacyShield !== "function") fail("PrivacyShield is a class", `got ${typeof PrivacyShield}`);
  else ok("PrivacyShield is a constructor");

  if (typeof PrivacyShieldAdmin !== "function") fail("PrivacyShieldAdmin is a class", `got ${typeof PrivacyShieldAdmin}`);
  else ok("PrivacyShieldAdmin is a constructor");

  if (!(new PrivacyShieldApiError(400, { error: "test", code: "TEST", detail: null }) instanceof Error))
    fail("PrivacyShieldApiError extends Error");
  else ok("PrivacyShieldApiError extends Error");
} catch (e) {
  fail("ESM import succeeded", String(e));
}

// ─── 3. EXPORT CHECK (CJS) ──────────────────────────────────────────────────

section("3. Exports — CJS (require)");

try {
  const require = createRequire(import.meta.url);
  const cjs = require(CJS_PATH);

  if (typeof cjs.PrivacyShield !== "function") fail("PrivacyShield exported from CJS", `got ${typeof cjs.PrivacyShield}`);
  else ok("PrivacyShield exported from CJS");

  if (typeof cjs.PrivacyShieldAdmin !== "function") fail("PrivacyShieldAdmin exported from CJS", `got ${typeof cjs.PrivacyShieldAdmin}`);
  else ok("PrivacyShieldAdmin exported from CJS");

  if (typeof cjs.PrivacyShieldApiError !== "function") fail("PrivacyShieldApiError exported from CJS", `got ${typeof cjs.PrivacyShieldApiError}`);
  else ok("PrivacyShieldApiError exported from CJS");
} catch (e) {
  fail("CJS require succeeded", String(e));
}

// ─── 4. CONSTRUCTOR GUARDS ──────────────────────────────────────────────────

section("4. Constructor Validation");

try {
  new PrivacyShield({});
  fail("PrivacyShield throws without apiKey");
} catch (e) {
  if (e.message.includes("apiKey is required")) ok("PrivacyShield throws without apiKey");
  else fail("PrivacyShield throws without apiKey", e.message);
}

try {
  new PrivacyShieldAdmin({});
  fail("PrivacyShieldAdmin throws without adminKey");
} catch (e) {
  if (e.message.includes("adminKey is required")) ok("PrivacyShieldAdmin throws without adminKey");
  else fail("PrivacyShieldAdmin throws without adminKey", e.message);
}

// Valid construction
try {
  const client = new PrivacyShield({ apiKey: "ps_test_abc123" });
  ok("PrivacyShield constructs with valid apiKey");
  if (typeof client.tokenize === "function") ok("client.tokenize is a method");
  else fail("client.tokenize is a method");
  if (typeof client.rehydrate === "function") ok("client.rehydrate is a method");
  else fail("client.rehydrate is a method");
  if (typeof client.flush === "function") ok("client.flush is a method");
  else fail("client.flush is a method");
  if (typeof client.health === "function") ok("client.health is a method");
  else fail("client.health is a method");
} catch (e) {
  fail("PrivacyShield constructs with valid apiKey", String(e));
}

// ─── 5. LIVE API TESTS ──────────────────────────────────────────────────────

section("5. Live API Tests");

if (!API_KEY || !ORG_ID) {
  console.log("  ⚠  Skipped — provide --api-key and --org-id for live tests");
  console.log(`     e.g.: node scripts/verify-build.mjs --api-key <key> --org-id <uuid>`);
} else {
  const client = new PrivacyShield({ apiKey: API_KEY, baseUrl: BASE_URL, timeoutMs: 10000 });
  // request_id must be a valid UUID (server validates format)
  const requestId = crypto.randomUUID();

  // 5a. Health
  try {
    const health = await client.health();
    if (health.status === "healthy") ok("health() → status: healthy");
    else fail("health() → status: healthy", `got: ${health.status}`);
  } catch (e) {
    fail("health() call succeeded", String(e));
  }

  // 5b. Tokenize
  let tokenizedText;
  let requestIdUsed;
  try {
    const result = await client.tokenize({
      texts: ["Il paziente Mario Rossi abita a Milano, CF RSSMRA80A01H501Z."],
      organizationId: ORG_ID,
      requestId,
    });

    if (Array.isArray(result.tokenizedTexts) && result.tokenizedTexts.length === 1)
      ok("tokenize() → returns tokenizedTexts array");
    else
      fail("tokenize() → returns tokenizedTexts array", JSON.stringify(result));

    if (Array.isArray(result.tokens))
      ok("tokenize() → returns tokens array");
    else
      fail("tokenize() → returns tokens array");

    const original = "Il paziente Mario Rossi abita a Milano, CF RSSMRA80A01H501Z.";
    if (result.tokenizedTexts[0] !== original)
      ok(`tokenize() → text was modified (PII detected)`);
    else
      console.log("  ⚠  tokenize() → text unchanged (NER model may not be running)");

    tokenizedText = result.tokenizedTexts[0];
    requestIdUsed = requestId;
    console.log(`     → tokenized: "${tokenizedText.substring(0, 80)}..."`);
  } catch (e) {
    fail("tokenize() call succeeded", String(e));
  }

  // 5c. Rehydrate (only if tokenize succeeded)
  if (tokenizedText && requestIdUsed) {
    try {
      const result = await client.rehydrate({
        text: tokenizedText,
        organizationId: ORG_ID,
        requestId: requestIdUsed,
      });

      if (typeof result.text === "string") ok("rehydrate() → returns text");
      else fail("rehydrate() → returns text", JSON.stringify(result));

      if (typeof result.rehydratedCount === "number") ok("rehydrate() → returns rehydratedCount");
      else fail("rehydrate() → returns rehydratedCount");

      console.log(`     → rehydrated: "${result.text.substring(0, 80)}..."`);
    } catch (e) {
      fail("rehydrate() call succeeded", String(e));
    }

    // 5d. Flush
    try {
      const result = await client.flush({
        organizationId: ORG_ID,
        requestId: requestIdUsed,
      });

      if (typeof result.flushedCount === "number") ok(`flush() → flushed ${result.flushedCount} tokens`);
      else fail("flush() → returns flushedCount", JSON.stringify(result));
    } catch (e) {
      fail("flush() call succeeded", String(e));
    }
  }

  // 5e. Error handling
  try {
    const badClient = new PrivacyShield({ apiKey: "ps_invalid_key", baseUrl: BASE_URL });
    await badClient.tokenize({
      texts: ["test"],
      organizationId: ORG_ID,
      requestId: crypto.randomUUID(),
    });
    fail("PrivacyShieldApiError thrown on 401", "no error thrown");
  } catch (e) {
    if (e instanceof PrivacyShieldApiError && e.statusCode === 401)
      ok("PrivacyShieldApiError thrown on 401 with correct statusCode");
    else if (e instanceof PrivacyShieldApiError)
      ok(`PrivacyShieldApiError thrown (statusCode: ${e.statusCode})`);
    else
      fail("PrivacyShieldApiError thrown on invalid key", String(e));
  }
}

// ─── SUMMARY ────────────────────────────────────────────────────────────────

console.log(`\n${"═".repeat(64)}`);
console.log(`  Results: ${passed} passed, ${failed} failed`);
console.log(`${"═".repeat(64)}\n`);

if (failed > 0) process.exit(1);
