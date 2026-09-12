# Deploying the AdFlow AI backend

Netlify hosts the **frontend only**. The backend is a normal containerised
FastAPI app with Postgres, Redis, object storage and FFmpeg, and it goes to a
persistent application platform (Fly.io, Railway, Render, a VPS, ECS — anything
that runs a container and gives you a volume or S3).

Nothing in this document is optional if you intend to spend money on real
providers: the budget guard, the webhook secret and the CORS list are what stop
a public endpoint from spending your balance.

## 1. Build and run

```bash
docker build -t adflow-api ./backend

# Release step — run migrations ONCE per deploy, not on every boot.
docker run --rm --env-file .env adflow-api alembic upgrade head

# Web
docker run -p 8000:8000 --env-file .env adflow-api

# Worker (only when JOB_BACKEND=celery)
docker run --env-file .env adflow-api \
  celery -A app.worker.celery_app worker --loglevel=info --concurrency=2
```

`docker compose up` runs the whole stack locally, including Postgres, Redis and
MinIO.

## 2. Health endpoints

| Endpoint | Meaning | Use it for |
|---|---|---|
| `GET /health` | the process is alive | container healthcheck, restarts |
| `GET /ready` | database + storage + queue + FFmpeg all usable | load-balancer gating, rolling deploys |

`/ready` returns **503** with a per-dependency breakdown when anything a render
needs is missing, so a broken instance never receives traffic.

## 3. Environment

Every variable lives in `.env.example` with a comment. The ones that matter
most in production:

| Variable | Why it matters |
|---|---|
| `ENV=production` | switches CORS to fail-closed and logging to JSON |
| `CORS_ORIGINS` | must list the exact frontend origin. A wildcard is refused in production |
| `DATABASE_URL` | Postgres, not SQLite |
| `STORAGE_BACKEND=s3` + `S3_*` | media must not live on an ephemeral container disk |
| `JOB_BACKEND=celery` + `REDIS_URL` | so long renders survive a web restart |
| `WEBHOOK_SECRET` | without it every provider callback is rejected (fail-closed, on purpose) |
| `FORCE_MOCK_PROVIDERS=false` | the switch that lets real, paid providers run |
| `INTEGRATION_TEST_BUDGET_USD` | caps what a connectivity test may ever spend |
| `SECRET_KEY` | anything but the development default |
| `ALLOW_DEV_LOGIN=false` | the demo login must not exist in production |

**Provider credentials belong here — never in Netlify, never in a
`NEXT_PUBLIC_*` variable.** The browser never sees them.

## 4. Storage

Local disk is for development. In production set `STORAGE_BACKEND=s3` and point
`S3_ENDPOINT_URL` / `S3_BUCKET` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` at AWS S3,
Cloudflare R2, Backblaze B2 or MinIO. `PUBLIC_MEDIA_BASE_URL` must be the URL a
browser can actually reach the bucket on.

Originals, generated media, renders, exports, thumbnails and audio all live
there. Binaries are never stored in Postgres.

## 5. Rendering capacity

Rendering is CPU work: roughly 3–8 seconds of CPU per second of finished video
on a small instance. Give the container at least 2 vCPUs and 2 GB RAM, and run
the worker separately from the web process so a long render never delays an
HTTP request. `ENABLE_LOCAL_RENDER=false` disables rendering on an instance that
should only serve the API.

## 6. Connecting the frontend

Once the API has a public URL, set in Netlify → Environment variables:

```
NEXT_PUBLIC_API_BASE_URL=https://api.your-domain.com
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_DEMO_MODE=false
```

Then verify, in this order, before treating mock mode as retired: CORS from the
deployed origin, authentication, an upload, job status polling, a real render,
QC and an export. Demo mode stays in the codebase either way — it is how the
product is demonstrated without spending anything.

## 7. What is NOT done for you

- No provider account is created, and no key is invented. `GET /api/v1/system/providers`
  lists exactly which keys are missing.
- Vendor endpoints and model IDs in `app/providers/catalog.py` are
  **configuration with documented defaults**, not verified facts. Confirm each
  against the vendor's current documentation before enabling it — every one is
  overridable by an environment variable so no code change is needed.
- No DNS, TLS or CDN configuration.
