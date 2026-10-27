const MAX_SUBTITLE_BYTES = 2 * 1024 * 1024;
const MAX_UPLOAD_REQUEST_BYTES = 3 * 1024 * 1024;
const MAX_BATCH_FILES = 20;
const MAX_BATCH_FILE_BYTES = 8 * 1024 * 1024;
const MAX_BATCH_REQUEST_BYTES = MAX_BATCH_FILE_BYTES + 64 * 1024;
const MAX_SEARCH_RESULTS = 200;
const ALLOWED_FORMATS = new Set(["srt", "ass", "ssa"]);
const KANA_RATIO_LIMIT = 0.20;
const PUBLIC_UPLOADS_PER_IP_HOUR = 60;
const PUBLIC_NEW_UPLOADS_PER_DAY = 1000;
const CODE_RE = /^(?:FC2(?:-?PPV)?-?\d{5,8}|(?:\d+)?[A-Za-z]{2,8}-\d{3,8}|[A-Za-z]{2,8}\d{3,8})(?:-CD\d+)?$/i;

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/health") {
        await env.DB.prepare("SELECT 1 AS ok").first();
        return json({ ok: true, version: "v1", service: "chickenrice-subtitle-pool" });
      }
      if (request.method === "POST" && url.pathname === "/api/v1/subtitles") {
        return await uploadSubtitle(request, env);
      }
      if (request.method === "POST" && url.pathname === "/api/v1/subtitles/batch") {
        return await uploadSubtitleBatch(request, env);
      }
      if (request.method === "GET" && url.pathname === "/api/v1/subtitles/search") {
        return await searchSubtitles(url, env);
      }
      const downloadMatch = url.pathname.match(/^\/api\/v1\/subtitles\/([0-9a-f-]+)\/download$/i);
      if (request.method === "GET" && downloadMatch) {
        return await downloadSubtitle(downloadMatch[1], env);
      }
      const deleteMatch = url.pathname.match(/^\/api\/v1\/admin\/subtitles\/([0-9a-f-]+)$/i);
      if (request.method === "DELETE" && deleteMatch) {
        return await removeSubtitle(request, deleteMatch[1], env);
      }
      return apiError(404, "not_found", "route not found");
    } catch (error) {
      console.error("unhandled pool error", error);
      return apiError(500, "internal_error", "internal server error");
    }
  },
};

async function uploadSubtitle(request, env) {
  const uploadMode = await authorizeUploadKey(request, env);
  if (!uploadMode) {
    return apiError(401, "invalid_upload_key", "invalid upload key");
  }
  if (uploadMode === "public") {
    const rate = await consumePublicIpRate(request, env);
    if (!rate.allowed) {
      return apiError(429, "public_upload_rate_limited", "public upload rate limit exceeded", {
        "Retry-After": String(rate.retryAfter),
      });
    }
  }
  const length = Number(request.headers.get("content-length") || 0);
  if (length > MAX_UPLOAD_REQUEST_BYTES) {
    return apiError(413, "file_too_large", "subtitle exceeds 2 MiB");
  }
  let form;
  try {
    form = await request.formData();
  } catch {
    return apiError(400, "invalid_multipart", "invalid multipart body");
  }
  const result = await prepareAndStoreSubtitle(
    form.get("file"),
    {
      code: form.get("code"),
      format: form.get("format"),
      language: form.get("language"),
    },
    uploadMode,
    env,
  );
  if (result.httpStatus) {
    return apiError(result.httpStatus, result.error, result.message, result.headers);
  }
  if (result.status === "created") {
    return json(result.item, 201);
  }
  if (result.status === "duplicate") {
    return json(result.item, 200, { "X-Pool-Deduplicated": "true" });
  }
  if (result.status === "removed") {
    return apiError(410, "subtitle_removed", "subtitle was removed by the pool administrator");
  }
  if (result.status === "daily_limited") {
    return apiError(429, "public_upload_daily_limit", "public upload daily limit exceeded", {
      "Retry-After": String(result.retryAfter),
    });
  }
  throw new Error(`unexpected upload status: ${result.status}`);
}

async function uploadSubtitleBatch(request, env) {
  const uploadMode = await authorizeUploadKey(request, env);
  if (!uploadMode) {
    return apiError(401, "invalid_upload_key", "invalid upload key");
  }
  if (uploadMode === "public") {
    const rate = await consumePublicIpRate(request, env);
    if (!rate.allowed) {
      return apiError(429, "public_upload_rate_limited", "public upload rate limit exceeded", {
        "Retry-After": String(rate.retryAfter),
      });
    }
  }
  const length = Number(request.headers.get("content-length") || 0);
  if (length > MAX_BATCH_REQUEST_BYTES) {
    return apiError(413, "batch_too_large", "batch exceeds 8 MiB");
  }
  let form;
  try {
    form = await request.formData();
  } catch {
    return apiError(400, "invalid_multipart", "invalid multipart body");
  }
  let manifest;
  try {
    manifest = JSON.parse(String(form.get("manifest") || ""));
  } catch {
    return apiError(400, "invalid_manifest", "manifest must be valid JSON");
  }
  if (!Array.isArray(manifest) || manifest.length === 0 || manifest.length > MAX_BATCH_FILES) {
    return apiError(400, "invalid_batch_size", `batch must contain 1-${MAX_BATCH_FILES} files`);
  }
  const files = manifest.map((_, index) => form.get(`file_${index}`));
  let totalBytes = 0;
  for (const file of files) {
    if (file && typeof file.arrayBuffer === "function") totalBytes += file.size;
  }
  if (totalBytes > MAX_BATCH_FILE_BYTES) {
    return apiError(413, "batch_too_large", "batch files exceed 8 MiB");
  }

  const items = [];
  for (let index = 0; index < manifest.length; index++) {
    const metadata = manifest[index] || {};
    const result = await prepareAndStoreSubtitle(files[index], metadata, uploadMode, env);
    const item = { index };
    if (result.httpStatus) {
      item.status = "error";
      item.error = result.error;
      item.message = result.message;
    } else if (result.status === "created") {
      item.status = "created";
      item.id = result.item.id;
      item.sha256 = result.item.sha256;
    } else if (result.status === "duplicate") {
      item.status = "duplicate";
      item.id = result.item.id;
      item.sha256 = result.item.sha256;
    } else if (result.status === "removed") {
      item.status = "removed";
      item.sha256 = result.sha256;
    } else if (result.status === "daily_limited") {
      item.status = "daily_limited";
      item.sha256 = result.sha256;
      item.retryAfter = result.retryAfter;
    }
    items.push(item);
  }
  const summary = {
    created: items.filter((item) => item.status === "created").length,
    duplicate: items.filter((item) => item.status === "duplicate").length,
    removed: items.filter((item) => item.status === "removed").length,
    error: items.filter((item) => item.status === "error").length,
    daily_limited: items.filter((item) => item.status === "daily_limited").length,
  };
  return json({ items, summary });
}

async function prepareAndStoreSubtitle(file, metadata, uploadMode, env) {
  const prepared = await prepareSubtitleUpload(file, metadata);
  if (prepared.error) return prepared.error;
  return storePreparedSubtitle(prepared.artifact, uploadMode, env);
}

async function prepareSubtitleUpload(file, metadata) {
  if (!file || typeof file.arrayBuffer !== "function") {
    return { error: { httpStatus: 400, error: "missing_file", message: "file field is required" } };
  }
  if (file.size <= 0 || file.size > MAX_SUBTITLE_BYTES) {
    return {
      error: {
        httpStatus: 413,
        error: "file_too_large",
        message: "subtitle must be between 1 byte and 2 MiB",
      },
    };
  }
  const format = String(metadata.format || extensionOf(file.name) || "").toLowerCase();
  if (!ALLOWED_FORMATS.has(format)) {
    return {
      error: {
        httpStatus: 415,
        error: "unsupported_format",
        message: "only SRT, ASS and SSA are accepted",
      },
    };
  }
  const language = String(metadata.language || "zh").toLowerCase();
  if (!["zh", "chi", "zho"].includes(language)) {
    return {
      error: {
        httpStatus: 415,
        error: "unsupported_language",
        message: "only Chinese subtitles are accepted",
      },
    };
  }
  const code = normalizeCode(String(metadata.code || "")) || normalizeAdditionalUploadCode(String(metadata.code || ""));
  if (!code) {
    return { error: { httpStatus: 400, error: "invalid_code", message: "a valid media code is required" } };
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return {
      error: { httpStatus: 422, error: "invalid_encoding", message: "subtitle must be UTF-8" },
    };
  }
  if (text.includes("\u0000")) {
    return {
      error: { httpStatus: 422, error: "invalid_subtitle", message: "subtitle contains NUL bytes" },
    };
  }
  let durationSeconds;
  try {
    validateChineseText(text);
    durationSeconds = parseSubtitleDuration(text, format);
  } catch (error) {
    return {
      error: { httpStatus: 422, error: "invalid_subtitle", message: error.message },
    };
  }
  return {
    artifact: {
      bytes,
      code,
      format,
      durationSeconds,
      sha256: await sha256Hex(bytes),
    },
  };
}

async function storePreparedSubtitle(artifact, uploadMode, env) {
  const { bytes, code, format, durationSeconds, sha256 } = artifact;
  const existing = await env.DB.prepare(
    "SELECT * FROM subtitle_items WHERE sha256 = ?"
  ).bind(sha256).first();
  if (existing) {
    if (existing.status === "removed") {
      return { status: "removed", sha256 };
    }
    return { status: "duplicate", item: toPublicItem(existing, true) };
  }
  if (uploadMode === "public") {
    const daily = await consumePublicDailyNewUpload(env);
    if (!daily.allowed) {
      return { status: "daily_limited", sha256, retryAfter: daily.retryAfter };
    }
  }
  const id = crypto.randomUUID();
  const uploadedAt = Date.now();
  const r2Key = `subtitles/${sha256.slice(0, 2)}/${sha256}.${format}`;
  const contentType = format === "srt" ? "text/plain; charset=utf-8" : "text/x-ssa; charset=utf-8";
  await env.BUCKET.put(r2Key, bytes, {
    httpMetadata: {
      contentType,
      cacheControl: "public, max-age=31536000, immutable",
    },
  });
  try {
    await env.DB.prepare(
      `INSERT INTO subtitle_items (
        id, canonical_code, display_code, language, format, duration_seconds,
        size_bytes, sha256, r2_key, uploaded_at, status
      ) VALUES (?, ?, ?, 'zh', ?, ?, ?, ?, ?, ?, 'active')`
    ).bind(
      id,
      code.canonical,
      code.display,
      format,
      durationSeconds,
      bytes.byteLength,
      sha256,
      r2Key,
      uploadedAt,
    ).run();
  } catch (error) {
    const raced = await env.DB.prepare(
      "SELECT * FROM subtitle_items WHERE sha256 = ?"
    ).bind(sha256).first();
    if (raced) {
      return { status: "duplicate", item: toPublicItem(raced, true) };
    }
    await env.BUCKET.delete(r2Key);
    throw error;
  }
  return {
    status: "created",
    item: {
      id,
      code: code.display,
      canonical_code: code.canonical,
      language: "zh",
      format,
      duration_seconds: durationSeconds,
      size_bytes: bytes.byteLength,
      sha256,
      uploaded_at: uploadedAt,
      created: true,
    },
  };
}

async function searchSubtitles(url, env) {
  const matchWork = url.searchParams.get("match") === "work";
  const inputs = matchWork && url.searchParams.has("codes")
    ? url.searchParams.getAll("codes")
    : [url.searchParams.get("code") || ""];
  const codes = inputs.map((value) => matchWork
    ? normalizeWorkCode(value.trim().replace(/[-_ ](?:CD|PART)[-_ ]?\d+$/i, ""))
    : normalizeCode(value));
  if (codes.length === 0 || codes.some((code) => !code)) {
    return apiError(400, "invalid_code", matchWork
      ? "a valid code is required for every alias"
      : "code is required");
  }
  const rawDuration = url.searchParams.get("duration");
  let duration = null;
  if (rawDuration !== null && rawDuration !== "") {
    const parsed = Number(rawDuration);
    if (!Number.isFinite(parsed) || parsed <= 0 || parsed > 86400) {
      return apiError(400, "invalid_duration", "duration must be between 1 and 86400 seconds");
    }
    duration = Math.floor(parsed);
  }
  const requestedLimit = Number(url.searchParams.get("limit") || MAX_SEARCH_RESULTS);
  const limit = Number.isFinite(requestedLimit)
    ? Math.max(1, Math.min(MAX_SEARCH_RESULTS, Math.floor(requestedLimit)))
    : MAX_SEARCH_RESULTS;
  const aliases = [...new Set(codes.flatMap((code) => matchWork ? code.storageKeys : [code.canonical]))];
  const predicate = matchWork
    ? `EXISTS (
         SELECT 1 FROM json_each(?) AS aliases
         WHERE canonical_code = aliases.value OR (
           canonical_code GLOB (aliases.value || '-cd[0-9]*')
           AND substr(canonical_code, length(aliases.value) + 4) NOT GLOB '*[^0-9]*'
         )
       )`
    : "canonical_code = ?";
  const rows = await env.DB.prepare(
    `SELECT * FROM subtitle_items
     WHERE (${predicate}) AND status = 'active'
     ORDER BY
       CASE WHEN duration_seconds IS NULL THEN 1 ELSE 0 END,
       CASE WHEN ? IS NULL THEN 0 ELSE ABS(duration_seconds - ?) END,
       size_bytes DESC,
       uploaded_at DESC${matchWork ? "" : " LIMIT ?"}`
  ).bind(
    matchWork ? JSON.stringify(aliases) : aliases[0],
    duration,
    duration,
    ...(matchWork ? [] : [limit]),
  ).all();
  return json({
    code: codes[0].display,
    items: (rows.results || []).map((row) => toPublicItem(row, false)),
  }, 200, { "Cache-Control": "public, max-age=30, stale-while-revalidate=60" });
}

async function downloadSubtitle(id, env) {
  const row = await env.DB.prepare(
    "SELECT * FROM subtitle_items WHERE id = ? AND status = 'active'"
  ).bind(id).first();
  if (!row) {
    return apiError(404, "subtitle_not_found", "subtitle not found");
  }
  const object = await env.BUCKET.get(row.r2_key);
  if (!object) {
    return apiError(410, "subtitle_object_missing", "subtitle object is unavailable");
  }
  const filename = `${safeFilename(row.display_code)}.${row.format}`;
  const contentType = row.format === "srt"
    ? "text/plain; charset=utf-8"
    : "text/x-ssa; charset=utf-8";
  return new Response(object.body, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(row.size_bytes),
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Cache-Control": "public, max-age=31536000, immutable",
      "ETag": `"${row.sha256}"`,
      "X-Content-SHA256": row.sha256,
    },
  });
}

async function removeSubtitle(request, id, env) {
  if (!(await hasValidBearer(request, env.ADMIN_KEY))) {
    return apiError(401, "invalid_admin_key", "invalid admin key");
  }
  const row = await env.DB.prepare(
    "SELECT * FROM subtitle_items WHERE id = ?"
  ).bind(id).first();
  if (!row) {
    return apiError(404, "subtitle_not_found", "subtitle not found");
  }
  if (row.status === "removed") {
    return json({ ok: true, id, removed: true });
  }
  await env.DB.prepare(
    "UPDATE subtitle_items SET status = 'removed', removed_at = ? WHERE id = ?"
  ).bind(Date.now(), id).run();
  await env.BUCKET.delete(row.r2_key);
  return json({ ok: true, id, removed: true });
}

function normalizeCode(value) {
  const trimmed = String(value || "").trim();
  const cdMatch = trimmed.match(/-CD(\d+)$/i);
  const cdIndex = cdMatch ? Number(cdMatch[1]) : null;
  const base = cdMatch ? trimmed.slice(0, -cdMatch[0].length) : trimmed;
  const lower = base.toLowerCase();
  const date = lower.match(/^(?:(?:1pondo|10musume|carib|caribbeancom|pacopacomama)[-_ ]?)?(\d{6})[-_](\d{3})$/);
  const nCode = lower.match(/^n[-_]?(\d{3,8})$/);
  const heyzo = lower.match(/^heyzo_(\d{3,8})$/);
  if (!CODE_RE.test(trimmed) && !date && !nCode && !heyzo) return null;
  let canonicalBase = lower;
  const compact = lower.match(/^([a-z]{2,8})(\d{3,8})$/);
  if (date) {
    canonicalBase = `${date[1]}-${date[2]}`;
  } else if (nCode) {
    canonicalBase = `n-${nCode[1]}`;
  } else if (heyzo) {
    canonicalBase = `heyzo-${heyzo[1]}`;
  } else if (compact) {
    const number = compact[2].replace(/^0+/, "") || "0";
    canonicalBase = `${compact[1]}-${number.padStart(3, "0")}`;
  } else if (lower.startsWith("fc2")) {
    const fc2 = lower.match(/fc2-?ppv-?(\d+)/) || lower.match(/fc2-?(\d+)/);
    if (fc2) canonicalBase = `fc2-${fc2[1].replace(/^0+/, "") || "0"}`;
  } else {
    const prefixed = lower.match(/^\d+([a-z]{2,8}-\d{3,8})$/);
    if (prefixed) canonicalBase = prefixed[1];
  }
  const canonical = cdIndex === null ? canonicalBase : `${canonicalBase}-cd${cdIndex}`;
  const display = canonical.toUpperCase();
  return { canonical, display };
}

function normalizeWorkCode(value) {
  const lower = String(value || "").trim().toLowerCase();
  const date = lower.match(/^(?:(?:1pondo|10musume|carib|caribbeancom|pacopacomama)[-_ ]?)?(\d{6})[-_](\d{2,5})$/);
  if (date) {
    const canonical = `${date[1]}-${date[2]}`;
    return { canonical, display: canonical.toUpperCase(), storageKeys: [canonical] };
  }

  const fc2 = lower.match(/^fc2[-_ ]?(?:ppv[-_ ]?)?(\d{3,12})$/);
  const nCode = lower.match(/^n[-_ ]?(\d{3,8})$/);
  const heyzo = lower.match(/^heyzo[-_ ]?(\d{1,8})$/);
  const ordinary = lower.match(/^((?:\d{2,4})?[a-z]{2,10})[-_ ]?(\d{1,7})$/)
    || lower.match(/^([a-z][a-z0-9]{1,9})[-_](\d{1,7})$/);
  const legacy = normalizeCode(lower);
  const legacyOrdinary = legacy?.canonical.match(/^([a-z]{2,8})-(\d{3,8})$/);
  let prefix, digits, maxWidth = 8;
  if (fc2) { prefix = "fc2"; digits = fc2[1]; maxWidth = 12; }
  else if (nCode) { prefix = "n"; digits = nCode[1]; }
  else if (heyzo) { prefix = "heyzo"; digits = heyzo[1]; }
  else if (ordinary) { prefix = ordinary[1]; digits = ordinary[2]; }
  else if (legacyOrdinary) { prefix = legacyOrdinary[1]; digits = legacyOrdinary[2]; }
  else return null;

  // These are the confirmed Core amateur aliases. Unknown numeric prefixes are not guessed.
  const amateurPrefixes = { mium: "300mium", gana: "200gana", jnt: "390jnt", idol: "250idol" };
  const shortPrefix = amateurPrefixes[prefix] ? prefix
    : Object.keys(amateurPrefixes).find((key) => amateurPrefixes[key] === prefix);
  const prefixes = new Set(shortPrefix ? [shortPrefix, amateurPrefixes[shortPrefix]] : [prefix]);
  const number = digits.replace(/^0+/, "") || "0";
  const storageKeys = new Set();
  for (const candidatePrefix of prefixes) {
    // Include legacy compact normalization and every legal stored zero-padding width.
    for (let width = number.length; width <= maxWidth; width++) {
      const candidate = `${candidatePrefix}-${number.padStart(width, "0")}`;
      storageKeys.add(candidate);
      const old = normalizeCode(candidate);
      const oldPrefix = old?.canonical.slice(0, old.canonical.lastIndexOf("-"));
      if (old && prefixes.has(oldPrefix)) storageKeys.add(old.canonical);
    }
  }
  const canonical = fc2 ? `fc2-${number}` : `${prefix}-${digits}`;
  return { canonical, display: canonical.toUpperCase(), storageKeys: [...storageKeys] };
}

function normalizeAdditionalUploadCode(value) {
  const trimmed = String(value || "").trim();
  const cd = trimmed.match(/-CD(\d+)$/i);
  const base = cd ? trimmed.slice(0, -cd[0].length) : trimmed;
  const parsed = normalizeWorkCode(base);
  if (!parsed) return null;
  const canonical = parsed.canonical + (cd ? `-cd${Number(cd[1])}` : "");
  return { canonical, display: canonical.toUpperCase() };
}

function validateChineseText(text) {
  let han = 0;
  let kana = 0;
  for (const char of text) {
    const point = char.codePointAt(0);
    if (point >= 0x4e00 && point <= 0x9fff) han++;
    else if (point >= 0x3040 && point <= 0x30ff) kana++;
  }
  if (han <= 0) throw new Error("no Chinese characters found");
  if (kana > 0 && kana / (han + kana) > KANA_RATIO_LIMIT) {
    throw new Error("subtitle appears to be Japanese");
  }
}

function parseSubtitleDuration(text, format) {
  let maximum = -1;
  if (format === "srt") {
    const pattern = /\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})/gm;
    for (const match of text.matchAll(pattern)) {
      maximum = Math.max(maximum, parseTimestamp(match[1]));
    }
  } else {
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim().toLowerCase().startsWith("dialogue:")) continue;
      const parts = line.split(",", 3);
      if (parts.length >= 3) maximum = Math.max(maximum, parseTimestamp(parts[2].trim()));
    }
  }
  if (!Number.isFinite(maximum) || maximum < 0) {
    throw new Error("subtitle duration could not be parsed");
  }
  return Math.floor(maximum);
}

function parseTimestamp(value) {
  const parts = String(value).replace(",", ".").split(":");
  if (parts.length !== 3) return -1;
  const seconds = Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2]);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.floor(seconds) : -1;
}

async function hasValidBearer(request, expected) {
  const header = request.headers.get("authorization") || "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match || !expected) return false;
  return timingSafeEqual(match[1], String(expected));
}

async function authorizeUploadKey(request, env) {
  const header = request.headers.get("authorization") || "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match) return null;
  const value = match[1];
  if (await timingSafeEqual(value, String(env.UPLOAD_KEY || ""))) return "trusted";
  if (env.PUBLIC_UPLOAD_KEY && await timingSafeEqual(value, String(env.PUBLIC_UPLOAD_KEY))) {
    return "public";
  }
  return null;
}

async function consumePublicIpRate(request, env) {
  if (!env.PUBLIC_RATE_SALT) {
    throw new Error("PUBLIC_RATE_SALT is not configured");
  }
  const now = Date.now();
  const window = Math.floor(now / 3_600_000);
  const expiresAt = (window + 1) * 3_600_000;
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const ipHash = await hmacHex(ip, env.PUBLIC_RATE_SALT);
  const count = await consumeLimitBucket(
    env,
    `ip:${ipHash}:${window}`,
    expiresAt,
    PUBLIC_UPLOADS_PER_IP_HOUR,
  );
  return {
    allowed: count !== null,
    retryAfter: Math.max(1, Math.ceil((expiresAt - now) / 1000)),
  };
}

async function consumePublicDailyNewUpload(env) {
  const now = new Date();
  const day = now.toISOString().slice(0, 10);
  const expiresAt = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + 1,
  );
  const count = await consumeLimitBucket(
    env,
    `new-content:${day}`,
    expiresAt,
    PUBLIC_NEW_UPLOADS_PER_DAY,
  );
  return {
    allowed: count !== null,
    retryAfter: Math.max(1, Math.ceil((expiresAt - Date.now()) / 1000)),
  };
}

async function consumeLimitBucket(env, bucketKey, expiresAt, limit) {
  const row = await env.DB.prepare(
    `INSERT INTO public_upload_limits(bucket_key, count, expires_at)
     VALUES (?, 1, ?)
     ON CONFLICT(bucket_key) DO UPDATE SET count = count + 1
     WHERE count < ?
     RETURNING count`
  ).bind(bucketKey, expiresAt, limit).first();
  return row ? Number(row.count) : null;
}

async function hmacHex(value, secret) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(value)));
  return [...signature].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function timingSafeEqual(left, right) {
  const encoder = new TextEncoder();
  const [leftHash, rightHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(left)),
    crypto.subtle.digest("SHA-256", encoder.encode(right)),
  ]);
  const a = new Uint8Array(leftHash);
  const b = new Uint8Array(rightHash);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function sha256Hex(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return [...digest].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function extensionOf(name) {
  const match = String(name || "").toLowerCase().match(/\.([a-z0-9]+)$/);
  return match ? match[1] : "";
}

function safeFilename(value) {
  return String(value || "subtitle").replace(/[^A-Za-z0-9._-]/g, "_");
}

function toPublicItem(row, includeCreated) {
  const item = {
    id: row.id,
    code: row.display_code,
    canonical_code: row.canonical_code,
    language: row.language,
    format: row.format,
    duration_seconds: row.duration_seconds,
    size_bytes: row.size_bytes,
    sha256: row.sha256,
    uploaded_at: row.uploaded_at,
    download_url: `/api/v1/subtitles/${row.id}/download`,
  };
  if (includeCreated) item.created = false;
  return item;
}

function json(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...headers,
    },
  });
}

function apiError(status, code, message, headers = {}) {
  return json({ error: code, message }, status, headers);
}
