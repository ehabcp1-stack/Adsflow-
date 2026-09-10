# CLAUDE.md — AdFlow AI (a TADAFQ product)

**Read this file before changing anything.** It preserves the product and
architectural rules of AdFlow AI. Future sessions must not casually violate
them. When a request conflicts with a rule here, say so and ask.

---

## 1. Product identity

| | |
|---|---|
| Parent brand | **TADAFQ** |
| Product | **AdFlow AI** |
| Display as | `AdFlow AI` with `by TADAFQ` underneath — never merged into one word |
| Category | Premium AI advertising **production** platform (not a video toy, not an admin dashboard) |

Initial specialisation — do not dilute it while adding new verticals:

- Arabic advertising, **Iraqi Arabic first**
- Iraqi-dialect voice-over
- Real-estate advertising
- Instagram Reels / Facebook Reels / TikTok-style vertical ads (9:16)

Core promise: the user gives a **tiny brief plus optional media**; AdFlow AI
analyses everything, develops the concept, writes the script, prepares the
voice, builds the storyboard, decides the production method per scene,
generates or reuses media, assembles the ad, checks quality and exports a
finished professional reel. **The UI must feel simple even though the system
is sophisticated.**

---

## 2. Official workflow — never skip an approval gate

```
Brief → AI Analysis → Concepts → Script → Voice → Storyboard
      → Production Plan → Approval → Production → Assembly & Editing
      → Final QC → Export
```

Frontend progress flow (`src/components/ProjectShell.tsx` → `STAGES`):
`brief · analyze · concepts · script · voice · storyboard · production · edit · qc · export`

The user must always know where they are. Every stage has a real route.

---

## 3. Project state machine

`backend/app/core/state_machine.py` is the single source of truth.

```
DRAFT → ANALYZING → ANALYSIS_READY → CONCEPT_REVIEW → CONCEPT_APPROVED
      → SCRIPT_REVIEW → SCRIPT_APPROVED → STORYBOARD_REVIEW → STORYBOARD_APPROVED
      → PRODUCTION_READY → GENERATING → EDITING → QC_REVIEW → FINAL_APPROVAL → EXPORTED
```
Supporting states: `PAUSED`, `FAILED`, `CANCELLED`.

Rules:

1. **Every transition is validated.** `set_state()` raises `InvalidStateTransition`
   on an illegal move. Never assign `project.state` directly.
2. **A stage may not run without its prerequisite approval**
   (`STAGE_PREREQUISITE_APPROVAL`). Routers call `approvals.require_approval()`.
3. **Downstream invalidation is mandatory.** If an upstream approved artifact
   changes, `approvals.invalidate_downstream()` invalidates dependent approvals
   and returns the project to the matching review state.
   *Example: script changes after storyboard approval → storyboard returns to
   `STORYBOARD_REVIEW`.*

---

## 4. Cost rules — the product's spine

**Never generate expensive AI video simply because it is available.**

Scene source priority (`SCENE_SOURCE_PRIORITY`, `model_router.choose_method`):

```
Original Video → Original Photo → Photo Motion → AI Image → AI Video
```

The AI Director may override this **only** for a meaningful quality benefit
(hook / hero shot / critical visual scene).

- Quality target: premium output; cost efficiency remains extremely important.
- Typical volume: ~4 finished reels/month, ideally **$20–$50/month** of AI
  production spend when source assets allow it.
- Premium ads may exceed that **only with explicit approval**.

Budget Guard (`services/costs.py`) is mandatory:

- Store Budget Limit, Estimated, Actual, Regeneration Reserve (20%), Remaining.
- **No paid provider action without `check_can_spend()` first.**
- Exceeding the budget raises `BudgetExceeded` (HTTP 402) and requires approval.
- Every billable operation writes a `CostEntry` (provider, model, operation,
  estimated, actual, currency, status, timestamp). Mock providers write $0 rows
  so the ledger shape is identical in demo mode.

Retry ladder (`providers/quality_judge.plan_retry`) — never infinite:
attempt 1 normal → attempt 2 optimized prompt → attempt 3 adjusted settings +
fallback provider. Always cost-checked.

---

## 5. Approval, versioning and locking

- Approvals carry `entity type · entity id · version · approved_by · approved_at
  · status · notes`.
- **Version, never overwrite** — Analysis, Concept, Script, Storyboard, Render
  and QC all keep history. Script refinement creates a **new version and keeps
  the selected concept**.
- **Locked scenes never regenerate accidentally.** Every mutation path calls
  `_assert_unlocked()`; locked scenes survive storyboard regeneration verbatim.

---

## 6. Provider abstraction — never couple to one vendor

Interfaces in `backend/app/providers/base.py`: `LLMProvider`, `ImageProvider`,
`VideoProvider`, `VoiceProvider`, `MusicProvider`.

- `providers/mock.py` — Mock adapters (structured Iraqi Arabic, real SVG frames,
  real MP4 clips when FFmpeg exists). **The whole product must stay usable on
  mocks.**
- `providers/adapters.py` — placeholders for OpenAI, Gemini, Veo, Runway,
  Seedance, ElevenLabs, music. Each documents exactly what to implement.
- `providers/registry.py` — resolution order: explicit → configured real adapter
  (key present *and* `FORCE_MOCK_PROVIDERS=false`) → Mock. Never breaks.
- `providers/model_router.py` — chooses provider/model from scene type, source
  material, quality level, reference strength, fidelity, cost and remaining
  budget. Quality levels: `economy | smart_premium (default) | maximum_quality`.
  Multi-model comparison is reserved for hook / hero / critical scenes only.

**Prompt Compiler rule:** the user-facing script is *never* sent to a video
provider. `providers/prompt_compiler.py` compiles structured production prompts
(subject, environment, composition, camera, lens feel, movement, lighting,
motion, timing, realism, constraints, references, negatives) and serialises them
per provider family.

---

## 7. Iraqi Arabic requirement

`backend/app/services/dialect.py` is a **dialect style layer**, not translation.

Presets: `iraqi_professional · iraqi_luxury · iraqi_emotional ·
iraqi_direct_sales · iraqi_friendly · iraqi_youth`.

- The spoken voice-over may differ from the written on-screen Arabic
  (`to_on_screen()` strips spoken fillers and shortens).
- Architecture exists for pronunciation rules, project-name / brand-name /
  number pronunciation, forbidden and preferred phrases, tone rules — all
  overridable per Brand Kit.
- Never "translate MSA into Iraqi vocabulary". Write natural Iraqi phrasing.

---

## 8. RTL and languages

Arabic RTL is **day-one infrastructure**, never bolted on.

- `frontend/src/i18n/dictionary.ts` holds every user-facing string (ar + en).
- `LocaleProvider` sets `<html dir lang>`, swaps the font stack and provides
  locale-aware `num`, `money`, `timecode`, `date`.
- **Timecodes, prices, model IDs and file names always render LTR** via the
  `.ltr-nums` class, even inside Arabic text.
- Use logical CSS properties (`ms-*`, `me-*`, `start-*`, `end-*`) — never
  `ml-*`/`left-*`.
- Arabic captions are rendered by **our editing system** (`services/editing.py`
  caption engine: RTL, shaping, safe zones, line limits, templates, brand
  fonts). **Never ask a video model to draw final Arabic text.**

---

## 9. Design system — "Premium Creative Studio"

Main application: light. Storyboard / production / editing / preview areas may
switch to a **dark graphite workspace** (`.workspace`).

| Token | Value |
|---|---|
| canvas | `#F6F7F9` |
| surface | `#FFFFFF` |
| ink | `#101828` (soft `#344054`, muted `#667085`) |
| line | `#E7EAEE` |
| accent (electric blue) | `#2563EB` / dark `#1D4ED8` / soft `#EFF4FF` |
| graphite | `#0C0E12 … #2E333D` |
| radius | 14 / 18 / 24 px |
| shadow | very subtle (`card`, `lift`) |

Avoid: excessive gradients, glassmorphism, neon, gaming aesthetics, generic
corporate admin dashboards. Animations stay restrained.

UX rule: **one obvious primary action per screen** (Approve / Continue), with
Refine / Edit secondary. Advanced controls hide behind **Director Mode**
(provider, model, fallback, raw compiled prompt, generation settings, retries,
quality scores, manual override).

Main navigation stays minimal: Dashboard · Projects · Brands · Media Library ·
Settings. Do not add sections.

---

## 10. Production modes

`auto_smart` (default, recommended, decides per scene) plus:
`photo_voice_reel · video_remix_reel · hybrid_reel · full_ai_reel · offer_info_reel`.

- **Photo + Voice Reel is a first-class premium method**, not a fallback: Ken
  Burns motion, push/pull, pan, controlled zoom, parallax, animated typography,
  captions, music, VO, SFX, branding, CTA, end screen.
- **Video Remix** treats uploaded footage as source material the user owns:
  keep / trim / reorder / speed / reframe / crop / grade / stabilize / strip
  original audio / new VO / captions / branding / music / SFX / AI enhance /
  video-to-video.

---

## 11. Real-estate fidelity rule

**Never intentionally change the real design of an uploaded project.**

- Uploaded renders/photos marked `is_project_reference` are the source of truth.
- With fidelity locks on (default), the compiled prompt forbids inventing
  facades, floor counts, materials, signage or landscaping not visible in the
  references, and adds `invented building details` to the negative list.
- Prefer source project media whenever available. Keyframe approval exists so a
  human sees the frame **before** expensive AI-video generation.

---

## 12. Quality thresholds

| Check | Threshold |
|---|---|
| Scene Quality Judge | **90 / 100** (manual approval always allowed) |
| Final QC — approved | **90+** |
| Final QC — review recommended | 85–89 |
| Final QC — fix required | below 85 |

Final QC weighting: Visual 25 · Audio/Voice 20 · Arabic 15 · Marketing 20 ·
Brand 10 · Platform 10. **Critical errors override the score**: wrong phone
number, wrong project name, obvious Arabic error, severe product distortion,
missing CTA.

**Auto Fix repairs only the affected component** — caption error → re-render
captions only; pronunciation → regenerate that voice line only; bad scene →
regenerate that scene only; music too loud → remix audio only. Never force a
full regeneration when a smaller fix exists.

---

## 13. Netlify is the primary visual review environment

**The deployed Netlify site is the visual source of truth for the user.**
localhost is for engineering only — never ask the user to open it to review
work, and never report localhost as the preview URL.

Site: `adflow-ai-tadafq` · https://adflow-ai-tadafq.netlify.app
Netlify project id: `9ce98808-7572-44ce-9982-7709e71f2fb0`

After any meaningful frontend change:

1. `npm run typecheck && npm run lint && npm run demo:build` — all must pass.
2. Commit with sensible history.
3. Push the branch.
4. Let Netlify build and deploy (framework detection + `netlify.toml`).
5. Open the deployed URL and verify the changed routes there.
6. Report the Netlify URL, deploy status, branch, routes changed/verified,
   build status, runtime mode (MOCK or REAL BACKEND) and known limitations.

A major UI task is **not complete** until the deployed version is visually
usable. Verify the whole route list — not just the homepage:
`/ · dashboard · projects · projects/new · demo project · analysis · concepts ·
script · voice · storyboard · production · edit · qc · export · brands · media ·
settings` — plus Arabic RTL, the dark storyboard/production/edit workspaces,
media previews, and nested-route refresh.

Do not create duplicate Netlify projects. Do not reconnect a repository that is
already correctly connected. Do not disable checks to make a build pass — fix
the cause.

Local development still matters (hot reload, tests, debugging), and the local
preview must keep working. Note: running `next build` while `next dev` is live
corrupts `.next` — stop the dev server first.

## 13a. Runtime configuration — one layer, no scattered checks

`frontend/src/lib/config.ts` is the **only** place that reads `process.env` or
knows about hosts and ports. Three modes:

| Mode | When | Behaviour |
|---|---|---|
| `mock` | `NEXT_PUBLIC_DEMO_MODE=true`, or a deployed build with no API URL | answers from the bundled demo snapshot |
| `development` | local dev with a developer backend | talks to `http://localhost:8000` |
| `production` | `NEXT_PUBLIC_API_BASE_URL` set on a deployed build | talks to the public FastAPI API |

Rules:

- **Never hardcode `http://localhost:8000`** (or any host/port) in frontend
  code, and never bake it into a production bundle via `next.config`.
- `NEXT_PUBLIC_API_BASE_URL` is the canonical variable
  (`NEXT_PUBLIC_API_URL` is kept only as a legacy alias).
- A deployed build with no backend configured must fall back to mock, never to
  a broken-looking shell.
- Only `NEXT_PUBLIC_*` values may reach the browser. Provider credentials
  (OpenAI, Gemini, Veo, Runway, Seedance, ElevenLabs, music) stay server-side
  and are configured on the **backend host**, never in Netlify.
- The frontend stays a normal Next.js App Router app — Server Components and
  the Next.js runtime are preserved. `NEXT_STATIC_EXPORT=true` exists only as a
  drag-and-drop fallback; **do not** make static-only the primary architecture.
- Netlify hosts the frontend only. The FastAPI backend (Postgres, Redis,
  workers, S3) is **not** forced onto Netlify; it goes to a persistent
  application platform later, and mock mode is disabled only after the real
  workflow is confirmed working end to end.

---

## 13b. Demo Mode must stay honest

`NEXT_PUBLIC_DEMO_MODE=true` produces the static showcase (`frontend/src/lib/demo.ts`)
that runs with no backend, for hosting on Netlify.

Non-negotiable: **it must never pretend to be a working install.**

- The banner stating "static showcase, nothing is saved" stays visible.
- Simulated writes live in a session-only overlay that resets on reload; never
  add fake persistence, fake accounts, or fabricated results.
- Uploads and anything needing real compute are refused with a clear message
  that points at the local install — never silently faked.
- The snapshot is generated from a real seeded run (`npm run demo:snapshot`),
  never hand-written, so the showcase always reflects real product output.

## 14. Architecture map

```
backend/                       FastAPI modular monolith (no microservices)
  app/core/                    config · db · enums · errors · security · state_machine
  app/models/                  identity.py (org, user, brand kit, voice, asset)
                               workflow.py (project → export, approvals, costs, jobs)
  app/providers/               base · mock · adapters · registry · pricing
                               model_router · prompt_compiler · quality_judge
  app/services/                analysis · concepts · scripts · dialect · voices
                               storyboards · production · editing · qc · exports
                               costs · approvals · jobs · storage · media_placeholder
                               director
  app/api/                     auth · projects · workflow · production · library
  app/seed.py                  demo project «مدينة الورد», full workflow on mocks
  app/worker.py                optional Celery worker
frontend/                      Next.js 15 App Router · TypeScript · Tailwind
  src/i18n/                    dictionary + LocaleProvider (RTL/LTR)
  src/lib/                     api client · hooks · types
  src/components/              design system + shell + project frame + AI Director
  src/app/                     every route in §2
```

Jobs: `JOB_BACKEND=inline` (thread pool, zero infra, default) or `celery`
(Redis). Long generation never blocks an HTTP request.

Storage: local adapter in dev, S3-compatible (MinIO/AWS/R2) in production.
**Never store media binaries in Postgres.**

---

## 14b. Where to change things

| Change | File |
|---|---|
| New workflow stage | `core/state_machine.py` + `components/ProjectShell.tsx` |
| New provider | `providers/adapters.py` + `registry.py` + `pricing.py` + `model_router.py` |
| Cost/pricing | `providers/pricing.py` |
| Iraqi phrasing / presets | `services/dialect.py` + `providers/mock.py` |
| Editing styles / captions | `services/editing.py` |
| QC rules | `services/qc.py` |
| UI strings | `frontend/src/i18n/dictionary.ts` (both locales, always) |

---

## 15. Non-negotiables checklist

- [ ] Approval gates enforced; no stage runs without its prerequisite.
- [ ] Every state transition validated; downstream approvals invalidated.
- [ ] Budget checked before any paid action; every cost written to the ledger.
- [ ] Cheapest sufficient production method chosen per scene.
- [ ] Locked scenes never regenerate.
- [ ] Provider-agnostic: mocks keep the whole product usable.
- [ ] Compiled prompts, never the raw script, sent to media providers.
- [ ] Arabic captions rendered by our editor, RTL correct everywhere.
- [ ] Real-project fidelity preserved; no invented architecture.
- [ ] QC ≥ 90 to approve; critical errors override the score.
- [ ] `http://localhost:3000` renders after every change.
- [ ] Both `ar` and `en` strings added for any new UI text.
