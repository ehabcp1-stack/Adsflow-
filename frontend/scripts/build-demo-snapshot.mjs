/**
 * Build the Demo Mode snapshot.
 *
 * Captures every GET response of the seeded «مدينة الورد» project from a
 * running AdFlow AI API, copies the generated media next to it, and rewrites
 * absolute media URLs to site-relative ones. The result is a self-contained
 * showcase that runs on static hosting with no backend.
 *
 *   node scripts/build-demo-snapshot.mjs [apiBase]
 */
import { cp, mkdir, readdir, rename, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const API_BASE = process.argv[2] ?? 'http://localhost:8000';
const API = `${API_BASE}/api/v1`;
const ROOT = path.resolve(import.meta.dirname, '..');
const OUT_DIR = path.join(ROOT, 'public', 'demo');
const MEDIA_DIR = path.join(OUT_DIR, 'media');
const STORAGE_DIR = path.resolve(ROOT, '..', 'backend', 'storage');

async function get(pathname) {
  const response = await fetch(`${API}${pathname}`);
  if (!response.ok) throw new Error(`GET ${pathname} → ${response.status}`);
  return response.json();
}

/** Absolute API media URLs become site-relative so the demo works anywhere. */
function rewrite(value) {
  if (typeof value === 'string') {
    return value.includes('/media/') ? `/demo/media/${value.split('/media/')[1]}` : value;
  }
  if (Array.isArray(value)) return value.map(rewrite);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rewrite(item)]));
  }
  return value;
}

const projects = await get('/projects');
const demo = projects.items.find((item) => item.name === 'مدينة الورد') ?? projects.items[0];
if (!demo) throw new Error('No seeded project found — run `python -m app.seed` first.');

const p = `/projects/${demo.id}`;
const endpoints = {
  '/dashboard': '/dashboard',
  '/projects': '/projects',
  '/assets': '/assets',
  '/brands': '/brands',
  '/settings': '/settings',
  '/meta/options': '/meta/options',
  '/meta/providers': '/meta/providers',
  '/meta/voices': '/meta/voices',
  // Settings → Providers reads these three; they carry no secret values,
  // only setting *names* and booleans (see backend/app/api/system.py).
  '/system/providers': '/system/providers',
  '/system/pricing': '/system/pricing',
  '/system/health': '/system/health',
  [p]: p,
  [`${p}/analysis`]: `${p}/analysis`,
  [`${p}/concepts`]: `${p}/concepts`,
  [`${p}/script`]: `${p}/script`,
  [`${p}/voice`]: `${p}/voice`,
  [`${p}/storyboard`]: `${p}/storyboard`,
  [`${p}/production`]: `${p}/production`,
  [`${p}/production/status`]: `${p}/production/status`,
  [`${p}/edit`]: `${p}/edit`,
  [`${p}/qc`]: `${p}/qc`,
  [`${p}/export`]: `${p}/export`,
  [`${p}/costs`]: `${p}/costs`,
  [`${p}/archive`]: `${p}/archive`,
  [`${p}/jobs`]: `${p}/jobs`,
  [`/assets?project_id=${demo.id}`]: `/assets?project_id=${demo.id}`,
};

const snapshot = { projectId: demo.id, capturedAt: new Date().toISOString(), routes: {} };
for (const [key, pathname] of Object.entries(endpoints)) {
  snapshot.routes[key] = rewrite(await get(pathname));
  process.stdout.write(`  captured ${key}\n`);
}

await rm(OUT_DIR, { recursive: true, force: true });
await mkdir(MEDIA_DIR, { recursive: true });
await cp(STORAGE_DIR, MEDIA_DIR, { recursive: true });

/**
 * The renderer writes mastering-quality intermediates — correct for a
 * deliverable, far too heavy for a static demo that ships in the repository
 * and downloads over a phone connection. Every video is re-encoded once for
 * the web: 720x1280 is still unmistakably the real reel, at roughly a tenth
 * of the bytes.
 */
async function compressForWeb(dir) {
  const entries = await readdir(dir, { recursive: true });
  let before = 0;
  let after = 0;
  let converted = 0;
  for (const entry of entries) {
    if (!entry.endsWith('.mp4')) continue;
    const file = path.join(dir, entry);
    const original = (await stat(file)).size;
    before += original;
    if (original < 400_000) {
      after += original;
      continue;
    }
    const tmp = `${file}.web.mp4`;
    try {
      execFileSync(
        'ffmpeg',
        ['-hide_banner', '-nostdin', '-y', '-i', file,
         '-vf', 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280',
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-pix_fmt', 'yuv420p',
         '-movflags', '+faststart', '-c:a', 'aac', '-b:a', '96k', tmp],
        { stdio: 'ignore', timeout: 300_000 },
      );
      await rename(tmp, file);
      converted += 1;
    } catch {
      await rm(tmp, { force: true });
    }
    after += (await stat(file)).size;
  }
  return { before, after, converted };
}

const compression = await compressForWeb(MEDIA_DIR);
await writeFile(path.join(OUT_DIR, 'snapshot.json'), JSON.stringify(snapshot), 'utf8');

const files = await readdir(MEDIA_DIR, { recursive: true });
console.log(
  `\nDemo snapshot ready → public/demo/snapshot.json` +
    `\n  project : ${demo.name} (${demo.id})` +
    `\n  routes  : ${Object.keys(snapshot.routes).length}` +
    `\n  media   : ${files.length} entries copied` +
    `\n  video   : ${compression.converted} re-encoded for web, ` +
      `${(compression.before / 1e6).toFixed(1)}MB → ${(compression.after / 1e6).toFixed(1)}MB`,
);
