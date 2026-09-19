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

**Hero-frame-first (`REQUIRE_KEYFRAME_APPROVAL`, default on).** An AI-video
scene generates a still at the cheapest image tier, parks in `REVIEWING`, and
stops. `production.approve_keyframe()` is what queues the paid video job, and
the approved frame goes with it as the conditioning image — approval buys the
take *and* pins what it looks like. Rejecting spends nothing further;
approving twice does not buy it twice; local methods are never gated.

**Two ceilings, not one.** `costs.check_can_spend()` refuses against the
per-project budget *and* `MONTHLY_BUDGET_HARD_CAP_USD` for the calendar month
(read from the ledger by date, mock rows excluded). Neither ever falls back to
mock providers silently: a mock render looks like a deliverable and is not
one, so the refusal is loud.

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

### 6a. A contract that accepts anything is not a contract

`providers/schemas.py` is where model output stops being text and starts being
data, and every field a **branch** depends on must be closed there — an enum
value, a required key, a stated range. Not "documented as"; validated as.

This is not theory. `ScenePlan.production_method` was a free string and
`QCResult.scores` was `Dict[str, float]`, and one live run produced:

* a storyboard whose scenes were `kenburns_zoom_on_photo` and
  `text_card_cta_overlay` — plausible, descriptive, in no enum anywhere.
  Neither matched `LOCAL_METHODS`, so four scenes that should have been
  rendered from the customer's own photo with FFmpeg for nothing went to the
  image provider, which on that server is the mock. Four SVG stills, each
  marked `passed` at quality 95 and `real_media: true`; assembly found no
  clips and produced a placeholder reel;
* a QC report in the model's own vocabulary on the model's own scale
  (`dialect_authenticity: 0.92`, `overall: 0.68`), so five of the six weighted
  dimensions silently took their 85/90 defaults — and the sixth,
  `brand_consistency: 0`, meant nought *percent* and was read as nought out of
  a hundred, deleting ten points of the final score.

Nothing was broken. Every step did exactly what it was told with a value no
step recognised, and every step reported success. So:

- **Validate at the boundary, not at the branch.** A wrong answer caught in
  `schemas.py` costs one repair attempt; the same answer caught nowhere costs
  a production run and a reel.
- **Never route an unrecognised value to a default branch.** `else: → image
  provider` is how an unimplemented method still produced a file. Unknown
  raises.
- **`model_router.choose_method` honours a requested method only if it is a
  real `ProductionMethod`** — that field comes from a model, whatever the
  reason string used to claim.
- **Units are part of the contract.** `QCScores` requires all six weighted
  dimensions, 0–100, and converts a wholly 0–1 answer; a mixed-scale answer is
  a contradiction and fails rather than being guessed at.
- **`ScriptLine.role` is `hook | body | cta`** — six branches across three
  services compare it exactly. A live script marked every line `narrator`, so
  `hook`, `body` and `cta` were all derived empty; the voice preview speaks
  `script.hook`, was handed `""`, and produced silence the user reported as a
  preview that "cuts off straight away". `scripts.effective_roles()` is the
  one place that answers "which line is the hook", and it falls back to
  position — first line opens, last line asks — so a stored version written
  before this can still be read.
- **A derived field never silently becomes empty.** `""` as the fallback of a
  `next(...)` is how all three of those fields died quietly. Derive from what
  is there, or raise.

**Prompt Compiler rule:** the user-facing script is *never* sent to a video
provider. `providers/prompt_compiler.py` compiles structured production prompts
(subject, environment, composition, camera, lens feel, movement, lighting,
motion, timing, realism, constraints, references, negatives) and serialises them
per provider family.

---

## 6b. Real media engine — `backend/app/media/`

AdFlow AI produces **actual** 1080x1920 H.264/AAC files. This package is where
that happens, and nothing in it calls a paid API.

| Module | Responsibility |
|---|---|
| `ffmpeg.py` | process runner, capability probe, house encode settings |
| `probe.py` | FFprobe metadata + corruption detection — never trust the browser |
| `motion.py` | photo → motion clip (push/pull/pan/tilt/Ken Burns/controlled) |
| `remix.py` | real trim, speed, 9:16 reframe, grade, stabilise, concat |
| `align.py` | word timing for the voice-over; caption cues |
| `captions.py` | Arabic caption rasterisation |
| `overlays.py` | logo, CTA card, end screen, timed overlay graph |
| `audio.py` | voice + music + SFX mix, sidechain ducking, loudness mastering |
| `shots.py` | scene-cut detection and per-segment scoring |
| `motion_graphics.py` | offer/info cards — typography, never generated video |
| `assemble.py` | staged assembly with a per-stage report |

Rules:

- **Never assume an FFmpeg filter exists** — `capabilities()` probes the build.
- Every scene clip is normalised (1080x1920, 30fps, AAC track) so concatenation
  can never fail on a parameter mismatch. Concatenation uses the concat
  *filter*, not the demuxer: the demuxer's stream-copy path fails silently.
- Intermediates use `INTERMEDIATE_VIDEO_ENCODE` (ultrafast); only the master
  uses the quality settings.
- `services/media_bridge.py` is the only place that maps storage URLs to local
  paths, which is what makes `STORAGE_BACKEND=s3` work with no render changes.

### Arabic captions — the one that bites

Pillow with **Raqm** shapes and bidi-orders Arabic correctly, but only when it
is given **logical** text and `direction="rtl"`. Pre-shaping with
arabic-reshaper + python-bidi first (the common recipe) double-reverses it and
produces mirrored Arabic. `captions.shape_for_draw()` picks the right path and
falls back to reshaper+bidi only when Raqm is absent.

Most Arabic display fonts carry no Latin glyphs, so a line is laid out token by
token: Arabic runs right-to-left in the Arabic font, Latin/number runs
left-to-right in the Latin font. Install `fonts-noto-core` (the Docker image
does). Installing Cairo or Tajawal upgrades the look with no code change.

### Voice-first timing — the order is a constraint, not a preference

Captions are timed against the **measured** voice track (`media/align.py`),
never the script's estimate. The aligner prefers a vendor's own word timings
and estimates otherwise, labelling which it used. Estimation is Arabic-aware:
unwritten short vowels, held long vowels, shadda, and "ال" as part of the word
it attaches to. Surplus audio becomes silence *between* words — never one word
held for seconds — except the last, which holds to the end of the audio.

Captions are word-level: one frame per word, same card, only the highlight
moving. Three traps, each now covered by a test:

* Highlight by **position**, not by string — a line with a repeated word lit
  both and the highlight appeared to jump backwards.
* Size the box from the **un-highlighted** layout. Highlighting splits a run
  and adds a word gap; at one frame per word the box visibly breathes.
* Word frames need their own minimum-duration floor. The whole-card floor of
  0.8s silently dropped every one of them and the render burnt no captions.
* **Only the edges of a cue fade.** `TimedOverlay.fade` defaults to 0.18s in
  *and* out; applied per word frame it cross-dissolves two identical cards once
  per word — 40 of 112 frames below 60% opacity, several fully blank. The PNGs
  are pixel-identical throughout, so this is only visible by measuring the
  finished MP4. `expand_word_level` marks `cue_first`/`cue_last`; everything
  between them gets `fade_in=fade_out=0`.
* The overlay `enable` window is **half-open** (`gte*lt`). `between` is
  inclusive at both ends, so two abutting frames both draw on the boundary
  frame — invisible on an opaque bar, one pulse per word on a stroke-only card.

**The voice job releases the scene jobs.** It retimes every scene onto the
audio it produced, so a scene cut before the voice exists is cut to the
estimate and overruns its slot — the reel ran 29.1s against a 21.9s plan with
scenes overhanging by up to 37%. `start_production` dispatches only the voice;
`dispatch_jobs_waiting_on_voice()` releases the rest.


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

## 12b. QC measures the file before it asks a model

`services/qc_checks.py` runs deterministic checks against the rendered file —
existence, resolution, codec, audio track, loudness, captions actually drawn
and inside the safe zone, CTA present, phone matching the Brand Kit, project
name spoken — and a **measured failure outranks a model opinion**. A placeholder
render can never score as a deliverable.

Two rules about how those findings are *worded*, both learned the hard way:

- **A failed check never prints the sentence for passing.** `_check()` carries
  `fail_en`/`fail_ar` for every condition it asserts. Without them a reel with
  no sound listed, in red, "الريل بيه مسار صوتي" — the reel has an audio
  track — and the one panel the user must be able to trust said the opposite
  of the finding. A check that interpolates its own measurement ("the frame is
  540x960, it must be 1080x1920") reads correctly either way and is exempt;
  `tests/test_model_contracts.py` enforces the distinction.
- **A placeholder reel is named, not scored down.** Capping two dimensions at
  60 left a reel containing no footage reading "61 — needs fixing" beside
  complaints about its resolution: every one true, none of them the point.
  `qc.PLACEHOLDER_ISSUE` is a critical issue, listed first, and the QC screen
  leads with it.

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
  app/providers/               base · mock · adapters · registry · catalog · http
                               schemas · pricing · model_router · prompt_compiler
                               quality_judge
  app/media/                   ffmpeg · probe · motion · remix · captions · overlays
                               audio · shots · motion_graphics · assemble
  app/services/                analysis · assets · concepts · scripts · script_qa
                               dialect · voices · storyboards · production
                               scene_render · editing · qc · qc_checks · exports
                               costs · approvals · jobs · storage · media_bridge
                               media_placeholder · director
  app/api/                     auth · projects · workflow · production · library
                               system · webhooks
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
| Provider/model metadata | `providers/catalog.py` (never hardcode a model id elsewhere) |
| Hook variants for A/B testing | `services/hooks.py` |
| Word timing / caption cues | `media/align.py` |
| Render behaviour | `app/media/*` + `services/scene_render.py` |
| Deterministic QC checks | `services/qc_checks.py` |
| Iraqi language rules | `services/dialect.py` + `services/script_qa.py` |

---

## 14c. Jobs, idempotency and cancellation

- `create_job()` carries an **idempotency key**; an identical in-flight job is
  returned rather than duplicated. A double-clicked button must not become two
  paid provider calls.
- `claim_job()` is an atomic conditional UPDATE. Without it two workers can run
  the same job and two FFmpeg processes write the same file — which produces a
  corrupt clip that still looks plausible.
- `cancel_job()` is honest: a queued job costs nothing, a locally running job is
  discarded, and a job already submitted to a provider says plainly that any
  cost already incurred still stands.
- `api/webhooks.py` is **fail-closed**: no configured secret means every
  callback is rejected. Deliveries are idempotent and cost is never read from
  the payload.

---

## 14d. Production readiness

- `GET /health` = liveness. `GET /ready` = database + storage + queue + FFmpeg,
  503 with a per-dependency breakdown when something a render needs is missing.
- CORS in production uses the configured list only; a wildcard is refused.
- `core/logging.py` emits JSON with request/job/project ids and **redacts
  credentials on the way out** — call sites are not trusted to remember.
- The Docker image ships FFmpeg and Arabic fonts and runs as a non-root user.
  Migrations are a release step, never a boot step.
- `deploy/PRODUCTION.md` is the deployment guide.

---

## 14e. Iraqi script QA — second pass

`services/script_qa.py` reviews every generated script deterministically (no
model call, no cost) across natural Iraqi phrasing, unnecessary MSA, register,
sales pressure, clarity, hook strength, rhythm, CTA quality, specificity and
duration fit. It repairs what can be repaired safely and **keeps the original
if the repair scores worse**. The stored `ScriptVersion.score` is the QA score
of what the user is actually shown, not the generator's own optimism.

---

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
- [ ] Output is a real 1080x1920 H.264/AAC file, not a placeholder claiming to be one.
- [ ] Deterministic QC ran against the actual file before any model opinion.
- [ ] No credential can reach a log line, an error message or the browser.
- [ ] A repeated request cannot become a second paid job.
- [ ] Nothing claims to be verified against a live provider API unless it was.
- [ ] Every model id carries `docs_url` + `verified_at`, or is marked unverified.
- [ ] No paid video is bought before its keyframe is approved.
- [ ] Captions are timed to the measured audio, never to the plan.
- [ ] Monthly spend cap enforced; no silent downgrade to mocks.
- [ ] Every model-written field a branch depends on is validated closed (§6a);
      an unrecognised value raises rather than falling into a default branch.
- [ ] A failing QC check prints what failed, never the sentence for passing.
