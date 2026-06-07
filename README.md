# Oura Stress Extractor


A small web app that turns a screenshot of Oura’s **Daytime Stress** screen into a table of `(timestamp, stress zone)` rows. Oura provides no API for this data, so the extractor reconstructs it directly from the screenshot using OpenCV and Tesseract OCR.

> Extracted from the larger (unreleased) _daystar_ project as a standalone, shareable tool. The extraction core (`backend/app/extractor/`) is vendored from daystar’s `extractor/` package.


## Try it out

https://relax.codeome.net

## Screenshots

### Upload & Extract
Drop in a Daytime Stress screenshot, set the date, and click **Extract**.
![Upload Panel](assets/screenshot-upload.png)

### Original + Annotated Views
The extractor displays the original screenshot alongside an annotated version showing detected datapoints.
![Original and Annotated Screenshots](assets/screenshot-phones.png)

### Results Table
Every detected datapoint is reconstructed into a clean table.  
Click **Download CSV** to save the results.
![Extracted Datapoints](assets/screenshot-relax.png)

## Device Compatibility

|Device|Resolution|Status|
|---|---|---|
|iPhone SE (2020)|640×1136|Supported|
|Others|—|Need screenshots|

## Contribute a Screenshot (Help Add Device Support)

If your device isn’t supported, you can help by contributing a screenshot.

1. Open an issue titled “Device screenshot: <your device>”.
2. Attach your Daytime Stress screenshot.
3. Include your device model and resolution if known.

This helps expand support to more devices.

## How it works

1. **Mask** the chart to remove the zone labels ("Stressed", "Engaged", …).
2. **Detect dots** with `cv2.HoughCircles`.
3. **OCR the x-axis** time labels to anchor the chart's start/end times.
4. Map each dot's x-position to a 15-minute timeslot → timestamp, and its
   y-position to a stress zone.

### ⚠️ Fixed-resolution assumption

All the pixel geometry (dot x-range, crop bounds, OCR regions, the bundled mask)
assumes a **640×1136** screenshot (Oura on an iPhone SE/8-class device). Uploads of
other sizes are **rejected** rather than silently producing a wrong table. If you
capture on a different device, the constants in
`backend/app/extractor/core.py` and `image_helpers.py` need re-tuning.

## Develop Locally

**Backend** (needs Tesseract installed locally, or just use Docker):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (proxies `/api` → `127.0.0.1:8000`):

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

## Tests

```bash
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

The suite includes a **golden test** that pins the vendored core's output to the
daystar CLI's known-good result for the bundled 2026-02-10 sample, so the copy
can't silently drift. Tests run real OCR, so Tesseract must be installed
(`TESSERACT_CMD` overrides the binary path).

## Run with Docker Locally

```bash
docker compose up --build
# Caddy serves plain HTTP on http://localhost by default.
```

If Chrome keeps upgrading `http://localhost` to `https://localhost`, clear
`localhost` site data or open a fresh profile/incognito window. Chrome can cache
an HTTPS-only policy for `localhost` after earlier HTTPS testing.

## Deploy on Docker Host

1. Point a DNS A record at the server.
2. `cp .env.example .env` and set `CADDY_SITE_ADDR` and `CADDY_TLS_SNIPPET`.
3. `docker compose up -d --build`

Caddy terminates TLS, serves the static frontend, and reverse-proxies `/api/*`
to the backend. The site is **public and unauthenticated** — abuse is handled by
the per-IP rate limit, the in-flight cap, and Cloudflare (see below). Only
ports 80/443 are exposed; the backend and frontend containers are internal.
Caddy also sets security headers (HSTS, CSP, `nosniff`, frame denial), caps
`/api` upload bodies at 1 MB, and writes JSON access logs to stdout (`docker
compose logs caddy`).

> The CSP pins the one inline `<script>` in `frontend/index.html` by SHA-256 hash.
> If you change that snippet, regenerate the hash and update it in the `Caddyfile`.

### TLS modes

The compose stack supports both local and production TLS without committing any
private certs:

1. **Local default:** `CADDY_SITE_ADDR=http://localhost` and `CADDY_TLS_SNIPPET=no_tls`
   make Caddy serve the stack over plain HTTP on localhost.
2. **Production:** set `CADDY_SITE_ADDR=https://your-domain` and
   `CADDY_TLS_SNIPPET=tls_origin`, then mount your Cloudflare Origin cert/key
   into `./certs/origin.pem` and `./certs/origin-key.pem` (read-only) before
   starting the stack.

## Public deployment behind Cloudflare

For a public, unauthenticated deployment, put Cloudflare in front for free DDoS
absorption and to hide the origin IP. The per-IP daily limit (above) and the
in-flight concurrency cap protect CPU/RAM; Cloudflare handles the volumetric
layer.

1. **Add the domain to Cloudflare** and switch your registrar to Cloudflare's
   nameservers.
2. **Proxy the DNS record** — an `A` record for your domain → your server IP with
   the **orange cloud** (proxied) on.
3. **TLS.** Use the production TLS mode above with a **Cloudflare Origin
   Certificate** (Cloudflare dashboard → SSL/TLS → Origin Server) and set
   SSL/TLS mode to **Full (strict)**. The origin cert is valid for years, so
   there is no renewal burden.
4. **Lock the origin to Cloudflare.** Restrict your Hetzner firewall so ports
   80/443 only accept Cloudflare's IP ranges
   (<https://www.cloudflare.com/ips/>); otherwise bots can hit the origin IP
   directly and bypass Cloudflare. Those same ranges are listed as
   `trusted_proxies` in the `Caddyfile` so `{client_ip}` (and the access logs and
   per-IP limit) reflect the real visitor, not the Cloudflare edge.
5. *(Optional)* Add a Cloudflare rate-limiting rule for short-burst protection;
   the 24 h per-IP quota stays in the app since the free tier can't do long
   windows.

## API

`POST /api/extract` (multipart form)

| field          | type   | notes                                  |
| -------------- | ------ | -------------------------------------- |
| `file`         | file   | PNG/JPEG screenshot, 640×1136          |
| `date`         | string | `YYYY-MM-DD`, the day the chart covers |
| `include_image`| bool   | return annotated chart as base64 PNG   |

Returns `{ points, gaps, warnings, meta }` (plus `annotated_png` if requested).

`GET /api/health` → `{ "status": "ok" }`

### Limits & responses

OCR is CPU-bound, so the endpoint runs it off the event loop in a worker thread
and caps how much work is in flight at once:

| status | when                                                           |
| ------ | -------------------------------------------------------------- |
| `200`  | success                                                        |
| `413`  | upload larger than 1 MB (also rejected at the edge by Caddy)   |
| `422`  | bad date, undecodable image, wrong/oversized resolution, no dots|
| `429`  | per-IP daily limit reached (`Retry-After` set)                  |
| `500`  | unexpected error (details are logged server-side, not returned)|
| `503`  | server busy — too many extractions in flight (`Retry-After: 60`)|
| `504`  | a single extraction exceeded the timeout                        |

Env vars tune the throttle (defaults in parentheses):

| var                         | meaning                                          |
| --------------------------- | ------------------------------------------------ |
| `MAX_CONCURRENT_EXTRACTIONS`| OCR jobs running at once (`2`)                    |
| `MAX_INFLIGHT_EXTRACTIONS`  | running + queued before `503` (`6`)               |
| `EXTRACT_TIMEOUT_SECONDS`   | per-extraction timeout before `504` (`30`)        |
| `RATE_LIMIT_MAX`            | successful extractions per IP per window; `0` off (`10`)|
| `RATE_LIMIT_WINDOW_HOURS`   | rolling window for the per-IP limit (`24`)        |
| `RATE_LIMIT_DB`             | SQLite path for the counter (`/data/ratelimit.db` in Docker)|

Only **successful** (200) extractions count against `RATE_LIMIT_MAX`; the count
is keyed on the client IP (from the `X-Real-IP` header Caddy sets) and persists
in SQLite, so it survives restarts and redeploys.

## License

MIT — see [LICENSE](LICENSE).
