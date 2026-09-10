# AdFlow AI

**by TADAFQ** — a premium AI advertising production platform for Arabic (Iraqi
dialect first) vertical ads: Instagram Reels, Facebook Reels and TikTok-style
9:16 video.

Give it a small brief and a few photos. It analyses your material, develops the
concept, writes an Iraqi-Arabic script, prepares the voice-over, builds a
storyboard, decides the cheapest production method that still looks premium,
generates or reuses media, assembles the reel, runs quality control and exports
a finished ad.

**Everything below runs with zero API keys** — realistic Mock Providers cover
LLM, image, video, voice and music, and the demo project «مدينة الورد» is
seeded end-to-end.

---

## 1. Quick start (2 terminals, ~3 minutes)

```bash
# ── Terminal 1 · backend ────────────────────────────────────────────
cd backend
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env                              # optional, defaults work
python -m app.seed                                      # seeds the demo project
uvicorn app.main:app --reload --port 8000

# ── Terminal 2 · frontend ───────────────────────────────────────────
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** → Dashboard → «مدينة الورد».

| Service | URL |
|---|---|
| Frontend (live preview) | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| Media files | http://localhost:8000/media/... |

**Demo login:** `demo@tadafq.com` / `demo1234`
(local development auto-signs-in as the demo user — authentication never blocks
you; set `ALLOW_DEV_LOGIN=false` to require a token.)

Requirements: Python 3.11+, Node 20+. FFmpeg is optional — with it the mock
providers render real MP4 clips and the assembled reel is playable in the
browser; without it they fall back to SVG posters and everything still works.

---

## 2. What you can do in the browser

1. **Dashboard** — create a new ad, remix an existing video, see monthly AI
   spend, completed videos and recent projects.
2. **New project wizard** — 4 short steps (basics → audience & message → assets
   → review) instead of one intimidating form.
3. **Analyze** — watch the engine work (understanding brief → analyzing images →
   analyzing videos → checking asset quality → planning production → estimating
   cost), then read the readiness score, asset table and cost plan.
4. **Concepts** — three genuinely different concepts, scored on 10 dimensions,
   with refine actions (More Iraqi / More Luxury / More Emotional / More Sales).
5. **Script** — three variants, timed lines, on-screen copy, script critic,
   inline editing, refinements that never lose the selected concept.
6. **Voice** — Iraqi demo voices, speed/energy/emotion, preview, lock. Locking
   the voice drives storyboard timing.
7. **Storyboard** — dark graphite timeline, per-scene thumbnails, full scene
   detail (camera, lighting, transition, production method, model, cost), Make
   Cheaper / Make More Premium / Lock.
8. **Production** — the full plan and cost breakdown **before** any spend, the
   generation order (hook first, hero second), live job progress.
9. **Edit** — large 9:16 preview, editing styles, captions/music/branding/CTA
   toggles, track list; advanced controls behind **Director Mode**.
10. **QC** — weighted score, per-level checks, critical issues, component-scoped
    Auto Fix, final approval.
11. **Export** — master + variants (with/without captions, without music, voice
    only, clean, branded, thumbnail), file list, project archive, duplicate.

Also: **Brands** (brand kits with colors, fonts, phone, preferred/forbidden
phrases), **Media Library** (quality + hero scores per asset) and **Settings**
(provider status, which env key each real adapter needs).

Switch **AR / EN** in the sidebar at any time — the whole app flips direction.

---

## 3. Architecture

```
adflow-ai/
├─ CLAUDE.md                 product + architecture rules (read before changing anything)
├─ docker-compose.yml        Postgres · Redis · MinIO · backend · frontend
├─ .env.example              every variable, no secrets
├─ Makefile                  make dev / seed / test / build
├─ backend/                  FastAPI modular monolith
│  ├─ app/core/              config · db · enums · errors · security · state_machine
│  ├─ app/models/            identity.py · workflow.py (SQLAlchemy 2.0, UUIDs, timestamps)
│  ├─ app/providers/         base · mock · adapters · registry
│  │                         pricing · model_router · prompt_compiler · quality_judge
│  ├─ app/services/          analysis · concepts · scripts · dialect · voices · storyboards
│  │                         production · editing · qc · exports · costs · approvals
│  │                         jobs · storage · media_placeholder · director
│  ├─ app/api/               auth · projects · workflow · production · library
│  ├─ app/seed.py            demo project, full workflow on mocks
│  ├─ app/worker.py          optional Celery worker
│  ├─ alembic/               migrations
│  └─ tests/                 54 tests: state machine, approvals, budget, providers,
│                            versioning, locking, dialect, full HTTP journey
└─ frontend/                 Next.js 15 · App Router · TypeScript · Tailwind
   └─ src/
      ├─ i18n/               dictionary (ar + en) · LocaleProvider (RTL/LTR)
      ├─ lib/                api client · hooks · types
      ├─ components/         design system · shell · project frame · AI Director
      └─ app/                every route
```

**Modular monolith, not microservices.** Domain logic lives in `services/`;
routers stay thin; nothing in `services/` imports a vendor SDK directly.

### Database

`users · organizations · projects · assets · project_analyses · concepts ·
script_versions · storyboards · scenes · generation_jobs · provider_runs ·
renders · cost_entries · brand_kits · voice_profiles · qc_reports · exports ·
approvals · performance_metrics`

UUID primary keys, created/updated timestamps, proper relationships, Alembic
migrations. SQLite by default (zero setup); set `DATABASE_URL` to Postgres for
docker/production.

---

## 4. Setup details

### Environment

```bash
cp .env.example .env
```

Both apps read it. `backend` loads `.env` from the repo root or `backend/`;
the frontend only needs `NEXT_PUBLIC_API_URL`. **Never put provider keys in a
`NEXT_PUBLIC_*` variable** — they would ship to the browser.

### Database

Default (nothing to install):

```
DATABASE_URL=sqlite:///./adflow.db
```

Postgres:

```bash
export DATABASE_URL=postgresql+psycopg://adflow:adflow@localhost:5432/adflow
cd backend && alembic upgrade head && python -m app.seed
```

Useful commands:

```bash
alembic upgrade head                       # apply migrations
alembic revision --autogenerate -m "..."   # new migration after model changes
alembic downgrade base                     # tear down
python -m app.seed --reset                 # drop + rebuild + reseed the demo
```

### Docker

```bash
docker compose up --build
```

Starts Postgres, Redis, MinIO, the API (port 8000) and the frontend (port 3000),
runs migrations and seeds the demo project automatically. MinIO console:
http://localhost:9001 (`adflow` / `adflow123`).

Local development without Docker is fully supported and is the fastest loop —
use `make dev`.

### Workers

V1 defaults to `JOB_BACKEND=inline`: a thread pool inside the API process. No
Redis needed, and HTTP requests never block on generation. To scale out:

```bash
export JOB_BACKEND=celery REDIS_URL=redis://localhost:6379/0
celery -A app.worker.celery_app worker --loglevel=info
```

Both backends run the same handlers against the same `generation_jobs` rows, so
the UI polls one endpoint either way.

---

## 5. How mock providers work

`FORCE_MOCK_PROVIDERS=true` (default) makes `providers/registry.py` serve the
Mock adapter for every capability.

| Capability | Mock behaviour |
|---|---|
| LLM | Structured Iraqi-Arabic content: brief interpretation, strategy, 3+2 concepts with 10-dimension scores, 3 script variants with timing, storyboard scenes, QC findings, refinements |
| Image | Real branded SVG frames written to storage — visible in every screen |
| Video | Real short MP4 via FFmpeg when available, SVG poster otherwise |
| Voice | Real duration estimates from the Iraqi speech model + a silent audio track so the timeline has real audio; reports what a real provider *would* cost |
| Music | Track state + duration + BPM |

Mock runs cost **$0** but still write `CostEntry` rows and `ProviderRun` records,
so the ledger, budget guard and Director Mode look exactly like production.

### Adding a real provider

1. Implement the adapter in `backend/app/providers/adapters.py` (each class
   documents the exact call and response mapping it needs).
2. Add its models to `providers/pricing.py::MODEL_PRICING`.
3. List it in `providers/model_router.py::MODEL_CANDIDATES` for the right
   method + quality level.
4. Put the key in `.env` and set `FORCE_MOCK_PROVIDERS=false`.

No domain service changes. The registry picks the real adapter up automatically
and falls back to the mock whenever the key is missing — the product never
breaks. Settings → AI providers shows which key each adapter is waiting for.

---

## 5a. Netlify — the primary review environment

**The deployed Netlify site is the visual source of truth**, not localhost.

| | |
|---|---|
| Site | `adflow-ai-tadafq` |
| URL | https://adflow-ai-tadafq.netlify.app |
| Project id | `9ce98808-7572-44ce-9982-7709e71f2fb0` |
| Config | `netlify.toml` (repo root) — `base = "frontend"`, `npm run build`, `publish = ".next"`, Node 20 |
| Adapter | `@netlify/plugin-nextjs` (the official Next.js Runtime), declared explicitly |
| Runtime today | **MOCK** — `NEXT_PUBLIC_DEMO_MODE=true` until the backend is public |

### Workflow

```
code → typecheck + lint + build → commit → push → Netlify build → verify deployed URL
```

One-time setup (Netlify → Site configuration → Build & deploy → Link repository)
connects the Git repo; after that every push to the production branch builds and
deploys automatically, and pull requests get Deploy Previews.

### Netlify environment variables

Set in **Site configuration → Environment variables** (also declared in
`netlify.toml` so a fresh deploy works out of the box):

| Variable | Today | Once the backend is public |
|---|---|---|
| `NEXT_PUBLIC_DEMO_MODE` | `true` | `false` |
| `NEXT_PUBLIC_APP_ENV` | `mock` | `production` |
| `NEXT_PUBLIC_API_BASE_URL` | *(unset)* | `https://api.your-domain.com` |
| `NODE_VERSION` | `20` | `20` |

**Never** add `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`,
`VEO_API_KEY`, `RUNWAY_API_KEY`, `SEEDANCE_API_KEY` or `MUSIC_API_KEY` to
Netlify. Those belong to the backend host only and must never be exposed
through a `NEXT_PUBLIC_` variable.

### Fallback: drag-and-drop deploy

If the repository is not linked yet, `deploy/netlify/site` holds a pre-built
static export (`npm run demo:export`). Drag that folder onto
https://app.netlify.com/projects/adflow-ai-tadafq/deploys — same site, same URL.
This is a fallback for convenience, not the architecture.

## 5b. Demo Mode (the hosted showcase)

`NEXT_PUBLIC_DEMO_MODE=true` builds a **fully static** version of the app that
answers every API call from a snapshot of the seeded «مدينة الورد» project —
no backend, no database, no keys. It is what gets hosted on Netlify so anyone
can browse the product from a link.

```bash
cd backend && uvicorn app.main:app --port 8000   # must be running & seeded
cd frontend
npm run demo:snapshot     # captures all GET routes + copies generated media
npm run demo:build        # static export → frontend/out/
```

What the snapshot contains (`frontend/public/demo/`): 23 API routes as JSON,
plus every generated SVG frame and MP4 clip, with media URLs rewritten to be
site-relative. Total ~520 KB.

Honesty rules baked in:

- A permanent banner says it is a static showcase and nothing is saved.
- Buttons still respond (approve, refine, switch editing style, toggle
  captions, export a variant) using a session-only overlay that resets on
  reload — enough to feel the product, never pretending to persist.
- Uploads are refused with a clear bilingual message pointing at the local
  install.
- Any screen the snapshot cannot answer shows "this needs the live API".

Deploying it (from a machine with normal internet access):

```bash
cd deploy/netlify
npx -y netlify-cli deploy --prod --dir=site --site <your-site-id>
```

Re-running `demo:snapshot` + `demo:build` and copying `frontend/out` into
`deploy/netlify/site` refreshes the showcase. Each deploy replaces the same
site at the same URL — Netlify keeps the previous deploys as rollback points,
it does not create duplicate sites.

## 6. Testing & quality

```bash
# backend
cd backend && .venv/bin/python -m pytest -q          # 54 tests
alembic upgrade head && alembic check                # migration check

# frontend
cd frontend
npm run typecheck                                    # tsc --noEmit
npm run lint
npm run build                                        # stop `npm run dev` first
```

Covered: project state transitions, approval requirements and downstream
invalidation, budget guard, versioning, locked-scene behaviour, provider
abstraction and routing, prompt compilation, retry ladder, cost entries, the
Iraqi dialect engine, and the complete HTTP journey from brief to export.

---

## 7. Environment variables

See `.env.example` for the full list. The ones that matter most:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./adflow.db` | Postgres in production |
| `FORCE_MOCK_PROVIDERS` | `true` | Set `false` to use real adapters |
| `JOB_BACKEND` | `inline` | `celery` to scale out |
| `STORAGE_BACKEND` | `local` | `s3` for MinIO/AWS/R2 |
| `DEFAULT_PROJECT_BUDGET_USD` | `12` | Per-project budget guard |
| `MONTHLY_BUDGET_TARGET_USD` | `50` | Dashboard target |
| `QC_APPROVE_THRESHOLD` | `90` | Final QC pass mark |
| `SCENE_QUALITY_THRESHOLD` | `90` | Scene judge pass mark |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Browser → API |

Provider keys (all optional): `OPENAI_API_KEY`, `GEMINI_API_KEY`,
`ELEVENLABS_API_KEY`, `RUNWAY_API_KEY`, `VEO_API_KEY`, `SEEDANCE_API_KEY`,
`MUSIC_API_KEY`.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| "ما نكدر نوصل للسيرفر" / "Cannot reach the API" | The backend is not running — start uvicorn on port 8000 |
| Frontend styles missing after a build | `next build` while `next dev` was running corrupts `.next`; stop dev, `rm -rf .next`, restart |
| No videos, only still frames | FFmpeg is not installed — everything still works, previews are posters |
| Fonts look plain | Google Fonts blocked/offline; the local fallback stack is used |
| `Demo user is not seeded` | `cd backend && python -m app.seed` |
| Netlify deploy succeeds but **every route 404s** | `publish` was missing, so Netlify shipped `frontend/` (the source tree) instead of the build. `netlify.toml` must set `publish = ".next"` and declare `@netlify/plugin-nextjs`. Check the deploy's file browser — if you see `src/`, `package.json` and `tsconfig.json`, that is the symptom. |

---

## 9. License / ownership

Internal TADAFQ product. Uploaded customer media stays the customer's property;
AdFlow AI treats it as source material to re-edit and re-brand.
