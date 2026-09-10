# Netlify deploy — AdFlow AI (Demo Mode)

`site/` is the pre-built static showcase (`npm run demo:build` in `frontend/`).
No build step runs on Netlify; the folder is published as-is.

## Deploy

```bash
cd "deploy/netlify"
npx -y netlify-cli login          # first time only, opens the browser
npx -y netlify-cli deploy --prod --dir=site --site adflow-ai-tadafq
```

Or drag the `site` folder onto
https://app.netlify.com/projects/adflow-ai-tadafq/deploys

Site id: `9ce98808-7572-44ce-9982-7709e71f2fb0`
URL:     https://adflow-ai-tadafq.netlify.app

## Refresh the showcase after changing the product

```bash
cd backend && uvicorn app.main:app --port 8000 &   # seeded backend
cd frontend && npm run demo:snapshot && npm run demo:build
rm -rf ../deploy/netlify/site && cp -r out ../deploy/netlify/site
```

Then deploy again — same site, same URL, previous deploys kept as rollbacks.
