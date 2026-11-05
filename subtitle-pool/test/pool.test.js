import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import worker from "../src/index.js";

const migration = [
  readFileSync(new URL("../migrations/0001_init.sql", import.meta.url), "utf8"),
  readFileSync(new URL("../migrations/0002_public_upload_limits.sql", import.meta.url), "utf8"),
  readFileSync(new URL("../migrations/0003_pool_stats.sql", import.meta.url), "utf8"),
].join("\n");

class Stmt {
  constructor(db, sql, args = []) {
    this.db = db;
    this.sql = sql;
    this.args = args;
  }

  bind(...args) {
    return new Stmt(this.db, this.sql, args);
  }

  async first() {
    return this.db.prepare(this.sql).get(...this.args) || null;
  }

  async all() {
    return { results: this.db.prepare(this.sql).all(...this.args) };
  }

  async run() {
    return this.db.prepare(this.sql).run(...this.args);
  }
}

class FakeD1 {
  constructor() {
    this.db = new DatabaseSync(":memory:");
    this.db.exec(migration);
  }

  prepare(sql) {
    return new Stmt(this.db, sql);
  }
}

class FakeR2 {
  constructor() {
    this.objects = new Map();
  }

  async put(key, bytes) {
    this.objects.set(key, new Uint8Array(bytes));
    return { key };
  }

  async get(key) {
    const bytes = this.objects.get(key);
    return bytes ? { body: bytes } : null;
  }

  async delete(key) {
    this.objects.delete(key);
  }
}

class FakeCache {
  constructor() {
    this.entries = new Map();
  }

  key(request) {
    return typeof request === "string" ? request : request.url;
  }

  async match(request) {
    const entry = this.entries.get(this.key(request));
    if (!entry) return null;
    return new Response(entry.body, { status: entry.status, headers: entry.headers });
  }

  async put(request, response) {
    this.entries.set(this.key(request), {
      status: response.status,
      headers: [...response.headers],
      body: await response.text(),
    });
  }

  async delete(request) {
    this.entries.delete(this.key(request));
  }
}

function env() {
  return {
    DB: new FakeD1(),
    BUCKET: new FakeR2(),
    UPLOAD_KEY: "upload-secret",
    PUBLIC_UPLOAD_KEY: "public-upload-secret",
    PUBLIC_RATE_SALT: "rate-test-salt",
    ADMIN_KEY: "admin-secret",
  };
}

function insertSubtitle(targetEnv, {
  code,
  duration = 120,
  size = 100,
  uploaded = 1000,
  status = "active",
}) {
  const id = crypto.randomUUID();
  targetEnv.DB.db.prepare(
    `INSERT INTO subtitle_items (
      id, canonical_code, display_code, language, format, duration_seconds,
      size_bytes, sha256, r2_key, uploaded_at, status
    ) VALUES (?, ?, ?, 'zh', 'srt', ?, ?, ?, ?, ?, ?)`
  ).run(id, code, code.toUpperCase(), duration, size, id, `${id}.srt`, uploaded, status);
  return id;
}

function subtitle(second, text = "你好，这是一段中文字幕") {
  return `1\n00:00:01,000 --> 00:00:${String(second).padStart(2, "0")},000\n${text}\n`;
}

async function upload(targetEnv, {
  code = "FNS-192",
  text = subtitle(10),
  filename = "FNS-192.srt",
  key = "upload-secret",
  ip = "203.0.113.10",
} = {}) {
  const form = new FormData();
  form.set("file", new File([text], filename, { type: "text/plain" }));
  form.set("code", code);
  form.set("format", filename.split(".").pop());
  form.set("language", "zh");
  return worker.fetch(new Request("https://pool.test/api/v1/subtitles", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "CF-Connecting-IP": ip,
    },
    body: form,
  }), targetEnv);
}

async function uploadBatch(targetEnv, items, {
  key = "public-upload-secret",
  ip = "203.0.113.20",
} = {}) {
  const form = new FormData();
  const manifest = items.map((item, index) => {
    form.set(`file_${index}`, new File(
      [item.text || subtitle(10)],
      item.filename || `FNS-${200 + index}.srt`,
      { type: "text/plain" },
    ));
    return {
      code: item.code || `FNS-${200 + index}`,
      format: item.format || "srt",
      language: "zh",
    };
  });
  form.set("manifest", JSON.stringify(manifest));
  return worker.fetch(new Request("https://pool.test/api/v1/subtitles/batch", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "CF-Connecting-IP": ip,
    },
    body: form,
  }), targetEnv);
}

test("health endpoint checks the D1 binding", async () => {
  const response = await worker.fetch(new Request("https://pool.test/health"), env());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    version: "v1",
    service: "chickenrice-subtitle-pool",
  });
});

test("upload requires the shared bearer key", async () => {
  const response = await upload(env(), { key: "wrong" });
  assert.equal(response.status, 401);
});

test("trusted and public upload keys are accepted but admin key is not", async () => {
  const targetEnv = env();
  const trusted = await upload(targetEnv, {
    text: subtitle(10, "可信密钥上传测试"),
  });
  const publicUpload = await upload(targetEnv, {
    key: "public-upload-secret",
    text: subtitle(11, "公开镜像密钥上传测试"),
  });
  const adminUpload = await upload(targetEnv, {
    key: "admin-secret",
    text: subtitle(12, "管理员密钥不能上传"),
  });

  assert.equal(trusted.status, 201);
  assert.equal(publicUpload.status, 201);
  assert.equal(adminUpload.status, 401);
});

test("batch upload reports created, duplicate and validation results independently", async () => {
  const targetEnv = env();
  const response = await uploadBatch(targetEnv, [
    { code: "BAT-001", text: subtitle(10, "批量上传第一个中文字幕") },
    { code: "BAT-002", text: subtitle(11, "批量上传第二个中文字幕") },
    { code: "BAT-001", text: subtitle(10, "批量上传第一个中文字幕") },
  ]);

  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.summary, {
    created: 2,
    duplicate: 1,
    removed: 0,
    error: 0,
    daily_limited: 0,
  });
  assert.deepEqual(body.items.map((item) => item.status), ["created", "created", "duplicate"]);
  const ipBucket = targetEnv.DB.db.prepare(
    "SELECT count FROM public_upload_limits WHERE bucket_key LIKE 'ip:%'"
  ).get();
  assert.equal(ipBucket.count, 1);
});

test("batch rejects more than twenty files", async () => {
  const targetEnv = env();
  const items = Array.from({ length: 21 }, (_, index) => ({
    code: `BIG-${300 + index}`,
    text: subtitle(10, `超大批量中文字幕 ${index}`),
  }));
  const response = await uploadBatch(targetEnv, items);
  assert.equal(response.status, 400);
});

test("batch applies daily new-content quota per file", async () => {
  const targetEnv = env();
  await uploadBatch(targetEnv, [
    { code: "DAY-001", text: subtitle(10, "每日额度准备") },
  ]);
  targetEnv.DB.db.prepare(
    "UPDATE public_upload_limits SET count = 999 WHERE bucket_key LIKE 'new-content:%'"
  ).run();

  const response = await uploadBatch(targetEnv, [
    { code: "DAY-002", text: subtitle(11, "额度内第一条") },
    { code: "DAY-003", text: subtitle(12, "额度外第二条") },
  ], { ip: "203.0.113.21" });
  const body = await response.json();

  assert.equal(body.summary.created, 1);
  assert.equal(body.summary.daily_limited, 1);
});

test("public key applies per-IP hourly rate limits while trusted key is exempt", async () => {
  const targetEnv = env();
  for (let index = 0; index < 60; index++) {
    const response = await upload(targetEnv, {
      key: "public-upload-secret",
      text: subtitle(10, `限流测试中文字幕 ${index}`),
    });
    assert.equal(response.status, 201);
  }
  const limited = await upload(targetEnv, {
    key: "public-upload-secret",
    text: subtitle(10, "超过每小时限流"),
  });
  const trusted = await upload(targetEnv, {
    text: subtitle(10, "可信密钥不受公开限流"),
  });

  assert.equal(limited.status, 429);
  assert.ok(Number(limited.headers.get("retry-after")) > 0);
  assert.equal(trusted.status, 201);
});

test("public daily new-content quota is enforced and duplicate does not consume it", async () => {
  const targetEnv = env();
  const first = await upload(targetEnv, {
    key: "public-upload-secret",
    text: subtitle(10, "重复内容不消耗每日新内容额度"),
  });
  const duplicate = await upload(targetEnv, {
    key: "public-upload-secret",
    text: subtitle(10, "重复内容不消耗每日新内容额度"),
  });
  assert.equal(first.status, 201);
  assert.equal(duplicate.status, 200);
  const dayBucket = targetEnv.DB.db.prepare(
    "SELECT count FROM public_upload_limits WHERE bucket_key LIKE 'new-content:%'"
  ).get();
  assert.equal(dayBucket.count, 1);

  targetEnv.DB.db.prepare(
    "UPDATE public_upload_limits SET count = 1000 WHERE bucket_key LIKE 'new-content:%'"
  ).run();
  const overLimit = await upload(targetEnv, {
    key: "public-upload-secret",
    text: subtitle(11, "超过每日新内容额度"),
    ip: "203.0.113.11",
  });
  assert.equal(overLimit.status, 429);
  assert.ok(Number(overLimit.headers.get("retry-after")) > 0);

  const trusted = await upload(targetEnv, {
    text: subtitle(12, "可信密钥不受每日公开额度限制"),
  });
  assert.equal(trusted.status, 201);
});

test("same content hash is idempotent and preserves CD suffix", async () => {
  const targetEnv = env();
  const first = await upload(targetEnv, {
    code: "ABC-001-CD2",
    filename: "ABC-001-CD2.srt",
  });
  const second = await upload(targetEnv, {
    code: "ABC-001-CD2",
    filename: "ABC-001-CD2.srt",
  });
  assert.equal(first.status, 201);
  assert.equal(second.status, 200);
  const firstBody = await first.json();
  const secondBody = await second.json();
  assert.equal(firstBody.code, "ABC-001-CD2");
  assert.equal(firstBody.canonical_code, "abc-001-cd2");
  assert.equal(secondBody.id, firstBody.id);
  assert.equal(targetEnv.DB.db.prepare("SELECT COUNT(*) AS n FROM subtitle_items").get().n, 1);
});

test("server rejects Japanese, unsupported formats and invalid UTF-8", async () => {
  const targetEnv = env();
  const japanese = await upload(targetEnv, {
    text: "1\n00:00:01,000 --> 00:00:02,000\nこれは日本語の字幕です\n",
  });
  assert.equal(japanese.status, 422);

  const unsupported = await upload(targetEnv, { filename: "FNS-192.vtt" });
  assert.equal(unsupported.status, 415);

  const form = new FormData();
  form.set("file", new File([new Uint8Array([0xff, 0xfe])], "FNS-192.srt"));
  form.set("code", "FNS-192");
  form.set("format", "srt");
  form.set("language", "zh");
  const invalid = await worker.fetch(new Request("https://pool.test/api/v1/subtitles", {
    method: "POST",
    headers: { Authorization: "Bearer upload-secret" },
    body: form,
  }), targetEnv);
  assert.equal(invalid.status, 422);
});

test("search uses duration distance, size and upload time ordering", async () => {
  const targetEnv = env();
  const now = Date.now();
  const insert = targetEnv.DB.db.prepare(
    `INSERT INTO subtitle_items (
      id, canonical_code, display_code, language, format, duration_seconds,
      size_bytes, sha256, r2_key, uploaded_at, status
    ) VALUES (?, 'fns-192', 'FNS-192', 'zh', 'srt', ?, ?, ?, ?, ?, 'active')`
  );
  insert.run("00000000-0000-4000-8000-000000000001", 110, 100, "a", "a.srt", now - 3);
  insert.run("00000000-0000-4000-8000-000000000002", 120, 100, "b", "b.srt", now - 2);
  insert.run("00000000-0000-4000-8000-000000000003", 120, 200, "c", "c.srt", now - 1);
  insert.run("00000000-0000-4000-8000-000000000004", 125, 999, "d", "d.srt", now);
  insert.run("00000000-0000-4000-8000-000000000005", 120, 200, "e", "e.srt", now + 1);

  const response = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?code=fns192&duration=120",
  ), targetEnv);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.items.map((item) => item.id.slice(-1)), ["5", "3", "2", "4", "1"]);
});

test("legacy single-code search keeps exact CD matching and its requested limit", async () => {
  const targetEnv = env();
  const base = insertSubtitle(targetEnv, { code: "abc-001" });
  const cd1 = insertSubtitle(targetEnv, { code: "abc-001-cd1" });
  insertSubtitle(targetEnv, { code: "abc-001-cd2" });
  insertSubtitle(targetEnv, { code: "abc-0010" });

  for (const [code, expected] of [["ABC-001", base], ["ABC-001-CD1", cd1]]) {
    const response = await worker.fetch(new Request(
      `https://pool.test/api/v1/subtitles/search?code=${code}&limit=1`,
    ), targetEnv);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.code, code);
    assert.deepEqual(body.items.map((item) => item.id), [expected]);
  }
});

test("work search merges repeated aliases before duration and size ordering", async () => {
  const targetEnv = env();
  const compact = insertSubtitle(targetEnv, { code: "crvr-426", size: 100 });
  const larger = insertSubtitle(targetEnv, { code: "crvr-00426-cd1", size: 200 });
  const farther = insertSubtitle(targetEnv, { code: "crvr-00426-cd2", duration: 121, size: 9999 });
  insertSubtitle(targetEnv, { code: "crvr-004260", size: 99999 });
  insertSubtitle(targetEnv, { code: "crvr-00426-cd1oops", size: 99999 });
  insertSubtitle(targetEnv, { code: "crvr-00426-cd3", status: "removed" });

  const response = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=CRVR00426&codes=CRVR-00426&codes=CRVR00426&duration=120&limit=1",
  ), targetEnv);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.items.map((item) => item.id), [larger, compact, farther]);
  assert.equal(body.items[0].code, "CRVR-00426-CD1");
  assert.equal(body.items[0].duration_seconds, 120);
  assert.equal(body.items[0].size_bytes, 200);
  assert.equal(body.items[0].sha256, larger);
  assert.equal(body.items[0].download_url, `/api/v1/subtitles/${larger}/download`);
});

test("work search falls back to code and ignores its CD or Part suffix", async () => {
  const targetEnv = env();
  const base = insertSubtitle(targetEnv, { code: "abc-001" });
  const cd1 = insertSubtitle(targetEnv, { code: "abc-001-cd1", size: 200 });
  const cd2 = insertSubtitle(targetEnv, { code: "abc-001-cd2", size: 300 });

  for (const code of ["ABC-001-CD2", "ABC-001-Part2"]) {
    const response = await worker.fetch(new Request(
      `https://pool.test/api/v1/subtitles/search?match=work&code=${code}`,
    ), targetEnv);
    assert.equal(response.status, 200);
    assert.deepEqual((await response.json()).items.map((item) => item.id), [cd2, cd1, base]);
  }
});

test("work search returns all candidates beyond the legacy cap", async () => {
  const targetEnv = env();
  for (let index = 1; index <= 205; index++) {
    insertSubtitle(targetEnv, { code: `abc-001-cd${index}`, size: index });
  }
  const response = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=ABC-001&limit=1",
  ), targetEnv);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.items.length, 205);
  assert.equal(body.items[0].code, "ABC-001-CD205");
  assert.equal(body.items.at(-1).code, "ABC-001-CD1");
});

test("new code spellings upload and search as equivalent without losing date zeros", async () => {
  const targetEnv = env();
  const groups = [
    ["010123-001", ["010123-001", "010123_001", "1pondo-010123_001", "10musume_010123-001", "carib-010123_001", "caribbeancom-010123-001", "pacopacomama_010123_001"]],
    ["HEYZO-1234", ["HEYZO-1234", "HEYZO1234", "HEYZO_1234"]],
    ["N-1234", ["N-1234", "N1234", "N_1234"]],
    ["FC2-1234567", ["FC2-1234567", "FC2-PPV-1234567", "FC2PPV-1234567"]],
    ["MIUM-1336", ["MIUM-1336", "300MIUM-1336"]],
  ];
  for (const [expectedCode, aliases] of groups) {
    const text = subtitle(10, `号码等价中文字幕 ${expectedCode}`);
    const created = await upload(targetEnv, { code: aliases[0], text });
    assert.equal(created.status, 201, aliases[0]);
    const item = await created.json();
    assert.equal(item.code, expectedCode);
    for (const code of aliases) {
      const duplicate = await upload(targetEnv, { code, text });
      assert.equal(duplicate.status, 200, code);
      assert.equal((await duplicate.json()).id, item.id, code);
      const response = await worker.fetch(new Request(
        `https://pool.test/api/v1/subtitles/search?code=${encodeURIComponent(code)}`,
      ), targetEnv);
      assert.equal(response.status, 200, code);
      assert.deepEqual((await response.json()).items.map((result) => result.id), [item.id], code);
    }
  }
});

test("work numeric aliases exclude nearby dates and preserve existing CD records", async () => {
  const targetEnv = env();
  const base = insertSubtitle(targetEnv, { code: "010123-001", size: 200 });
  const part = insertSubtitle(targetEnv, { code: "010123-001-cd2", size: 100 });
  insertSubtitle(targetEnv, { code: "010123-002", size: 9999 });
  insertSubtitle(targetEnv, { code: "010124-001", size: 9999 });
  const response = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=010123_001&codes=1pondo-010123-001-CD1",
  ), targetEnv);
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).items.map((item) => item.id), [base, part]);
});

test("work search validates aliases and duration and reports empty matches", async () => {
  const targetEnv = env();
  for (const query of ["match=work", "match=work&codes=", "match=work&codes=ABC-001&codes=wrong%25code"]) {
    const response = await worker.fetch(new Request(
      `https://pool.test/api/v1/subtitles/search?${query}`,
    ), targetEnv);
    assert.equal(response.status, 400, query);
    assert.equal((await response.json()).error, "invalid_code");
  }
  const invalidDuration = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=ABC-001&duration=0",
  ), targetEnv);
  assert.equal(invalidDuration.status, 400);
  assert.equal((await invalidDuration.json()).error, "invalid_duration");
  const noMatches = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=ABC-001",
  ), targetEnv);
  assert.equal(noMatches.status, 200);
  assert.deepEqual((await noMatches.json()).items, []);
});

test("work search finds legacy compact and zero-padded rows without changing exact search", async () => {
  const targetEnv = env();
  const compactResponse = await upload(targetEnv, { code: "SAVR00143", text: subtitle(10, "旧版紧凑番号字幕") });
  const paddedResponse = await upload(targetEnv, { code: "SAVR-00143", text: subtitle(10, "旧版保留前导零番号的中文字幕") });
  assert.equal(compactResponse.status, 201);
  assert.equal(paddedResponse.status, 201);
  const compact = await compactResponse.json();
  const padded = await paddedResponse.json();
  assert.equal(compact.canonical_code, "savr-143");
  assert.equal(padded.canonical_code, "savr-00143");
  const part = insertSubtitle(targetEnv, { code: "savr-000143-cd2", duration: 10, size: 50000 });
  const farther = insertSubtitle(targetEnv, { code: "savr-00000143-cd3", duration: 11, size: 99999 });
  for (const code of ["savr-001430", "savr-00144", "savr-000143-cd1oops", "savr-000143-cd"])
    insertSubtitle(targetEnv, { code, duration: 10, size: 999999 });
  insertSubtitle(targetEnv, { code: "savr-143-cd4", status: "removed" });
  const response = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=SAVR-00143&duration=10&limit=1",
  ), targetEnv);
  assert.equal(response.status, 200);
  const tied = [compact, padded].sort((a, b) => b.size_bytes - a.size_bytes);
  assert.deepEqual((await response.json()).items.map((item) => item.id), [part, ...tied.map((item) => item.id), farther]);
  for (const [code, id] of [["SAVR00143", compact.id], ["SAVR-00143", padded.id]]) {
    const exact = await worker.fetch(new Request(
      `https://pool.test/api/v1/subtitles/search?code=${code}`,
    ), targetEnv);
    assert.deepEqual((await exact.json()).items.map((item) => item.id), [id]);
  }
});

test("work search accepts Core query families and retrieves only seeded equivalent identities", async () => {
  const cases = [
    [["T28-1"], ["t28-1", "t28-0000001-cd2"], ["t28-2", "t29-1"]],
    [["AB-1"], ["ab-001", "ab-00000001-cd1"], ["ab-10", "ab-2"]],
    [["ABCDEFGHIJ-1234567"], ["abcdefghij-1234567", "abcdefghij-1234567-cd2"], ["abcdefghij-1234568"]],
    [["SAVR-1234567"], ["savr-01234567", "savr-1234567-cd1"], ["savr-1234568"]],
    [["300MIUM-00123", "MIUM-00123"], ["mium-123", "mium-000123-cd2", "300mium-00123"], ["mium-124", "200mium-00123", "gana-123"]],
    [["FC2-PPV-123", "FC2PPV-123", "FC2-123"], ["fc2-123", "fc2-123-cd1"], ["fc2-124"]],
    [["FC2-PPV-123456789012", "FC2PPV-123456789012", "FC2-123456789012"], ["fc2-123456789012", "fc2-123456789012-cd2"], ["fc2-123456789013"]],
    [["HEYZO-00123", "HEYZO_00123", "HEYZO00123"], ["heyzo-123", "heyzo-00000123-cd2"], ["heyzo-124"]],
    [["N-00123", "N_00123", "N00123"], ["n-123", "n-00000123-cd2"], ["n-124"]],
    [["010203-04", "010203_04"], ["010203-04", "010203-04-cd2"], ["010203-004", "010204-04", "010203-05"]],
    [["010203-00004", "010203_00004"], ["010203-00004", "010203-00004-cd2"], ["010203-04", "010203-004", "010203-00005"]],
  ];
  for (const [codes, same, wrong] of cases) {
    const targetEnv = env();
    const expected = same.map((code, index) => insertSubtitle(targetEnv, { code, size: 100 + index }));
    for (const code of wrong) insertSubtitle(targetEnv, { code, size: 999999 });
    const url = new URL("https://pool.test/api/v1/subtitles/search?match=work");
    for (const code of codes) url.searchParams.append("codes", code);
    const response = await worker.fetch(new Request(url), targetEnv);
    const body = await response.json();
    assert.equal(response.status, 200, JSON.stringify({ codes, body }));
    assert.deepEqual(body.items.map((item) => item.id), expected.reverse(), JSON.stringify(codes));
  }
});

test("newly supported uploads retain old canonical rules and are visible through work search", async () => {
  const cases = [
    ["T28-1", "t28-1"], ["AB-1", "ab-1"], ["ABCDEFGHIJ-1234567", "abcdefghij-1234567"],
    ["FC2-PPV-123", "fc2-123"], ["FC2PPV-123456789012", "fc2-123456789012"],
    ["010203_04", "010203-04"], ["010203-00004", "010203-00004"],
  ];
  for (const [code, canonical] of cases) {
    const targetEnv = env();
    const created = await upload(targetEnv, { code, text: subtitle(10, `新增号型中文字幕 ${code}`) });
    const item = await created.json();
    assert.equal(created.status, 201, JSON.stringify({ code, item }));
    assert.equal(item.canonical_code, canonical);
    const response = await worker.fetch(new Request(
      `https://pool.test/api/v1/subtitles/search?match=work&codes=${encodeURIComponent(code)}`,
    ), targetEnv);
    assert.equal(response.status, 200);
    assert.deepEqual((await response.json()).items.map((entry) => entry.id), [item.id]);
  }
});

test("work parser rejects polluted or out-of-range query tokens", async () => {
  const targetEnv = env();
  for (const code of ["SSIS-157-LTX", "T28-12345678", "FC2-PPV-1234567890123", "010203-4", "010203-123456", "A-1"]) {
    const response = await worker.fetch(new Request(
      `https://pool.test/api/v1/subtitles/search?match=work&codes=${encodeURIComponent(code)}`,
    ), targetEnv);
    assert.equal(response.status, 400, code);
  }
});

test("download returns the original bytes with an immutable hash ETag", async () => {
  const targetEnv = env();
  const created = await upload(targetEnv);
  const item = await created.json();
  const response = await worker.fetch(new Request(
    `https://pool.test/api/v1/subtitles/${item.id}/download`,
  ), targetEnv);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("etag"), `"${item.sha256}"`);
  assert.equal(await response.text(), subtitle(10));
});

test("admin deletion leaves a tombstone that blocks re-upload", async () => {
  const targetEnv = env();
  const created = await upload(targetEnv);
  const item = await created.json();
  const unauthorized = await worker.fetch(new Request(
    `https://pool.test/api/v1/admin/subtitles/${item.id}`,
    { method: "DELETE", headers: { Authorization: "Bearer wrong" } },
  ), targetEnv);
  assert.equal(unauthorized.status, 401);

  const removed = await worker.fetch(new Request(
    `https://pool.test/api/v1/admin/subtitles/${item.id}`,
    { method: "DELETE", headers: { Authorization: "Bearer admin-secret" } },
  ), targetEnv);
  assert.equal(removed.status, 200);
  assert.equal(targetEnv.BUCKET.objects.size, 0);

  const again = await upload(targetEnv);
  assert.equal(again.status, 410);
});

test("stats tracks active subtitles through upload, duplicate, batch and delete", async () => {
  const targetEnv = env();
  const stats = async () => worker.fetch(new Request(
    "https://pool.test/api/v1/stats",
  ), targetEnv);

  const initial = await stats();
  assert.equal(initial.status, 200);
  const initialBody = await initial.json();
  assert.equal(initialBody.subtitle_count, 0);
  assert.equal(typeof initialBody.queried_at, "string");
  assert.ok(initialBody.queried_at.length > 0);

  const first = await upload(targetEnv, { text: subtitle(10, "统计测试第一条") });
  assert.equal(first.status, 201);
  assert.equal((await (await stats()).json()).subtitle_count, 1);

  const duplicate = await upload(targetEnv, { text: subtitle(10, "统计测试第一条") });
  assert.equal(duplicate.status, 200);
  assert.equal((await (await stats()).json()).subtitle_count, 1);

  const batch = await uploadBatch(targetEnv, [
    { code: "STAT-002", text: subtitle(11, "统计测试第二条") },
    { code: "STAT-003", text: subtitle(12, "统计测试第三条") },
  ]);
  assert.equal(batch.status, 200);
  assert.equal((await (await stats()).json()).subtitle_count, 3);

  const item = await first.json();
  const removed = await worker.fetch(new Request(
    `https://pool.test/api/v1/admin/subtitles/${item.id}`,
    { method: "DELETE", headers: { Authorization: "Bearer admin-secret" } },
  ), targetEnv);
  assert.equal(removed.status, 200);
  assert.equal((await (await stats()).json()).subtitle_count, 2);

  const removedAgain = await worker.fetch(new Request(
    `https://pool.test/api/v1/admin/subtitles/${item.id}`,
    { method: "DELETE", headers: { Authorization: "Bearer admin-secret" } },
  ), targetEnv);
  assert.equal(removedAgain.status, 200);
  assert.equal((await (await stats()).json()).subtitle_count, 2);
});

test("search cache collapses identical work searches and exposes cache headers", async () => {
  const targetEnv = env();
  targetEnv.SEARCH_CACHE = new FakeCache();
  insertSubtitle(targetEnv, { code: "cache-001", duration: 100, size: 1000 });

  const first = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=cache-001&duration=100",
  ), targetEnv);
  assert.equal(first.status, 200);
  assert.equal(first.headers.get("x-pool-cache"), "MISS");
  const firstBody = await first.json();
  assert.equal(firstBody.items.length, 1);

  insertSubtitle(targetEnv, { code: "cache-001", duration: 100, size: 1000 });
  const second = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=cache-001&duration=100",
  ), targetEnv);
  assert.equal(second.status, 200);
  assert.equal(second.headers.get("x-pool-cache"), "HIT");
  assert.equal((await second.json()).items.length, 1);
});

test("search cache key ignores alias order but separates duration and limit", async () => {
  const targetEnv = env();
  targetEnv.SEARCH_CACHE = new FakeCache();
  const first = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=AA-001&codes=BB-002&duration=100",
  ), targetEnv);
  assert.equal(first.headers.get("x-pool-cache"), "MISS");
  const reordered = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=BB-002&codes=AA-001&duration=100",
  ), targetEnv);
  assert.equal(reordered.headers.get("x-pool-cache"), "HIT");
  const otherDuration = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=AA-001&codes=BB-002&duration=200",
  ), targetEnv);
  assert.equal(otherDuration.headers.get("x-pool-cache"), "MISS");

  const codeFirst = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?code=AA-001&limit=1",
  ), targetEnv);
  assert.equal(codeFirst.headers.get("x-pool-cache"), "MISS");
  const codeOtherLimit = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?code=AA-001&limit=2",
  ), targetEnv);
  assert.equal(codeOtherLimit.headers.get("x-pool-cache"), "MISS");
});

test("search negative cache stores empty results and expires past its deadline", async () => {
  const targetEnv = env();
  targetEnv.SEARCH_CACHE = new FakeCache();
  const emptyUrl = "https://pool.test/api/v1/subtitles/search?match=work&codes=ZZZ-999&duration=100";
  const first = await worker.fetch(new Request(emptyUrl), targetEnv);
  assert.equal(first.headers.get("x-pool-cache"), "MISS");
  assert.deepEqual((await first.json()).items, []);
  const second = await worker.fetch(new Request(emptyUrl), targetEnv);
  assert.equal(second.headers.get("x-pool-cache"), "HIT");
  assert.deepEqual((await second.json()).items, []);

  for (const entry of targetEnv.SEARCH_CACHE.entries.values()) {
    entry.headers = entry.headers.map(([key, value]) =>
      key.toLowerCase() === "x-pool-cache-expires" ? [key, "1"] : [key, value]);
  }
  const expired = await worker.fetch(new Request(emptyUrl), targetEnv);
  assert.equal(expired.headers.get("x-pool-cache"), "MISS");
});

test("search failures are never cached and cacheless runtimes report bypass", async () => {
  const failing = env();
  failing.SEARCH_CACHE = new FakeCache();
  failing.DB = { prepare() { throw new Error("database unavailable"); } };
  const failed = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=FAIL-001&duration=100",
  ), failing);
  assert.equal(failed.status, 500);
  assert.equal(failing.SEARCH_CACHE.entries.size, 0);

  const bypass = env();
  const response = await worker.fetch(new Request(
    "https://pool.test/api/v1/subtitles/search?match=work&codes=BYPASS-001&duration=100",
  ), bypass);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-pool-cache"), "BYPASS");
});
