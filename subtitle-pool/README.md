# ChickenRice Subtitle Pool

Cloudflare Worker + D1 + R2 subtitle index for the Subtitle Cloud uploader and
the Emby ChickenRicePool plugin.

For local-only testing, copy `.dev.vars.example` to `.dev.vars`, then run:

```powershell
npx wrangler d1 migrations apply chickenrice-pool --local
npx wrangler dev --local
```

`.dev.vars` is ignored by Git and must never contain production secrets reused
from a public machine.

## First deployment

1. Install dependencies and authenticate Wrangler:

   ```powershell
   npm install
   npx wrangler login
   npx wrangler d1 create chickenrice-pool
   npx wrangler r2 bucket create chickenrice-subtitles
   ```

2. Put the returned D1 database ID into `wrangler.toml`.
3. Apply the schema and create the two secrets:

   ```powershell
   npx wrangler d1 migrations apply chickenrice-pool --remote
   npx wrangler secret put UPLOAD_KEY
   npx wrangler secret put ADMIN_KEY
   npx wrangler deploy
   ```

4. Verify `GET /health`, upload a known SRT, search it by code, download it,
   and compare the SHA-256 before configuring Subtitle Cloud.

Subtitle Cloud v3.23 uploads in batches through
`POST /api/v1/subtitles/batch`: up to 20 files and 8 MiB per request. The
public image key allows 60 batch requests per IP per hour and 1,000 new
contents per day.

`UPLOAD_KEY` is distributed only to trusted Subtitle Cloud deployments.
`ADMIN_KEY` stays with the pool operator and is used by the removal API:

```powershell
$headers = @{ Authorization = "Bearer $env:POOL_ADMIN_KEY" }
Invoke-RestMethod -Method Delete -Headers $headers `
  -Uri "https://YOUR_WORKER/api/v1/admin/subtitles/SUBTITLE_ID"
```

The bucket stays private. Downloads always pass through the Worker.

## Subtitle Assistant search

Existing `GET /api/v1/subtitles/search?code=ABC-001-CD1` requests keep exact
CD matching and the existing `limit` behavior (up to 200 results).

The combined plugin uses repeated `codes` parameters with `match=work`:

```text
/api/v1/subtitles/search?match=work&codes=CRVR00426&codes=CRVR-00426&duration=7200
```

This mode merges all aliases and their valid `-CDn` records, ignores a CD/Part
suffix on the requested work, and returns every active candidate. `limit` is
ignored in this mode; the plugin applies its display limit after processing the
complete response. If `codes` is absent, a single `code` is accepted instead. The response
keeps `code` (the first normalized alias) and the existing `items` fields,
including `duration_seconds`, `size_bytes`, `sha256` and `download_url`.

Both modes sort known subtitle timelines first, then by distance from the
optional video `duration` in seconds, file bytes descending and upload time
descending. No matches return HTTP 200 with `items: []`. Missing/invalid codes
return HTTP 400 `invalid_code`; any invalid alias rejects the complete request.
An invalid duration retains HTTP 400 `invalid_duration`.

New uploads and searches also accept six-digit date codes with a hyphen or
underscore (for example `010123_001`), preserving both numeric parts and their
leading zeros. The optional `1pondo`, `10musume`, `carib`, `caribbeancom` and
`pacopacomama` prefixes are ignored. `HEYZO1234`/`HEYZO-1234`/`HEYZO_1234` and
`N1234`/`N-1234`/`N_1234` are equivalent. Existing FC2 PPV and numbered amateur
prefix normalization remains in place. Existing stored codes, IDs and download
URLs are retained; no database migration is required.

Run the Worker regression tests locally with `npm test` (Node.js with
`node:sqlite` support).
