# Netlify deploy — AdFlow AI

Netlify is the **primary visual review environment** for AdFlow AI.

| | |
|---|---|
| Site | `adflow-ai-tadafq` |
| URL | https://adflow-ai-tadafq.netlify.app |
| Project id | `9ce98808-7572-44ce-9982-7709e71f2fb0` |
| Dashboard | https://app.netlify.com/projects/adflow-ai-tadafq |

## Primary path — connect the Git repository (do this once)

The repo root already contains `netlify.toml` (`base = "frontend"`,
`npm run build`, Node 20, mock-mode env vars). Netlify's Next.js framework
detection handles the adapter — nothing here overrides it.

1. Push this repository to GitHub.
2. Netlify → **Site configuration → Build & deploy → Link repository**.
3. Pick the repo and branch. Netlify reads `netlify.toml`; leave the detected
   build settings alone.
4. Every push then builds and deploys automatically; pull requests get Deploy
   Previews.

Do **not** create a second Netlify project, and do not reconnect a repository
that is already correctly linked.

## Fallback — drag and drop (no repository needed)

`site/` is a pre-built static export of the demo build
(`cd frontend && npm run demo:export`). Use it to get a live URL immediately:

- Drag the `site` folder onto https://app.netlify.com/projects/adflow-ai-tadafq/deploys

or, from a machine with normal internet access:

```bash
cd deploy/netlify
npx -y netlify-cli login
npx -y netlify-cli deploy --prod --dir=site --site 9ce98808-7572-44ce-9982-7709e71f2fb0
```

This is a convenience path only. Once the repository is linked, deploy through
Git so the deployed site always matches committed code.

## Refresh the demo snapshot after product changes

```bash
cd backend && uvicorn app.main:app --port 8000 &   # seeded backend
cd frontend && npm run demo:snapshot               # re-capture API + media
npm run typecheck && npm run lint && npm run demo:build
# fallback folder only:
npm run demo:export && rm -rf ../deploy/netlify/site && cp -r out ../deploy/netlify/site
```

Each deploy replaces the same site at the same URL. Netlify keeps previous
deploys as rollback points — it never creates duplicate sites.

## Going live against the real backend

When the FastAPI backend is publicly hosted, set in Netlify → Environment
variables:

```
NEXT_PUBLIC_DEMO_MODE=false
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_API_BASE_URL=https://api.your-domain.com
```

then verify CORS, authentication, uploads, job status and provider requests
before treating mock mode as retired. Provider API keys belong to the backend
host — never to Netlify, and never to a `NEXT_PUBLIC_` variable.
