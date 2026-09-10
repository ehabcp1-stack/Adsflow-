'use client';

/**
 * Demo Mode — the showcase build.
 *
 * When NEXT_PUBLIC_DEMO_MODE=true the app answers every API call from a
 * snapshot of the seeded «مدينة الورد» project instead of the FastAPI
 * backend, so the whole product can be browsed on static hosting with no
 * server, no database and no API keys.
 *
 * It is deliberately a *showcase*, not a working install: nothing is stored,
 * uploads are refused with a clear message, and a banner says so. The real
 * product runs locally against the backend.
 */
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

type Snapshot = { projectId: string; capturedAt: string; routes: Record<string, any> };

let snapshotPromise: Promise<Snapshot> | null = null;

function loadSnapshot(): Promise<Snapshot> {
  if (!snapshotPromise) {
    snapshotPromise = fetch('/demo/snapshot.json', { cache: 'force-cache' }).then((response) => {
      if (!response.ok) throw new Error('demo snapshot missing');
      return response.json();
    });
  }
  return snapshotPromise;
}

/** Session-only overlay so buttons visibly do something. Resets on reload. */
const overlay: {
  state: string | null;
  approvals: Record<string, string>;
  editSettings: Record<string, unknown>;
  editingStyle: string | null;
  selectedConceptId: string | null;
  selectedScriptId: string | null;
  voiceProfileId: string | null;
  voiceLocked: boolean;
  extraExports: any[];
  extraBrands: any[];
} = {
  state: null,
  approvals: {},
  editSettings: {},
  editingStyle: null,
  selectedConceptId: null,
  selectedScriptId: null,
  voiceProfileId: null,
  voiceLocked: false,
  extraExports: [],
  extraBrands: [],
};

export class DemoUnavailable extends Error {
  code = 'demo_mode';
  messageAr: string;
  constructor(message: string, messageAr: string) {
    super(message);
    this.messageAr = messageAr;
  }
}

const clone = <T,>(value: T): T => (value === undefined ? value : JSON.parse(JSON.stringify(value)));

/** Any project id in the URL resolves to the single demo project. */
function normalize(path: string, projectId: string): string {
  return path.replace(/\/projects\/[0-9a-f-]{8,}/i, `/projects/${projectId}`);
}

function applyProjectOverlay(detail: any) {
  if (!detail) return detail;
  const next = clone(detail);
  if (overlay.state) next.state = overlay.state;
  if (overlay.selectedConceptId) next.selected_concept_id = overlay.selectedConceptId;
  if (overlay.selectedScriptId) next.selected_script_id = overlay.selectedScriptId;
  if (overlay.voiceProfileId) next.selected_voice_profile_id = overlay.voiceProfileId;
  if (overlay.voiceLocked) next.voice_locked = true;
  if (overlay.editingStyle) next.editing_style = overlay.editingStyle;
  next.edit_settings = { ...(next.edit_settings ?? {}), ...overlay.editSettings };
  for (const [entity, status] of Object.entries(overlay.approvals)) {
    next.approvals = next.approvals ?? {};
    next.approvals[entity] = { ...(next.approvals[entity] ?? {}), status };
  }
  return next;
}

function stageAfter(entity: string): string {
  return (
    {
      analysis: 'CONCEPT_REVIEW',
      concept: 'CONCEPT_APPROVED',
      script: 'SCRIPT_APPROVED',
      voice: 'SCRIPT_APPROVED',
      storyboard: 'STORYBOARD_APPROVED',
      production_plan: 'PRODUCTION_READY',
      final: 'FINAL_APPROVAL',
    }[entity] ?? 'DRAFT'
  );
}

export async function demoRequest<T>(method: string, path: string, body?: any): Promise<T> {
  const snapshot = await loadSnapshot();
  const { projectId, routes } = snapshot;
  const key = normalize(path.split('#')[0], projectId);
  const base = `/projects/${projectId}`;
  const route = (suffix: string) => clone(routes[`${base}${suffix}`]);

  // ── Reads ──────────────────────────────────────────────────────────
  if (method === 'GET') {
    if (key === `${base}`) return applyProjectOverlay(routes[base]) as T;
    if (key === '/projects' || key === '/projects?archived=false') return clone(routes['/projects']) as T;
    if (key.startsWith(`${base}/edit`)) {
      const payload = route('/edit');
      payload.settings = { ...payload.settings, ...overlay.editSettings };
      if (overlay.editingStyle) payload.editing_style = overlay.editingStyle;
      return payload as T;
    }
    if (key.startsWith(`${base}/export`)) {
      const payload = route('/export');
      payload.items = [...overlay.extraExports, ...payload.items];
      return payload as T;
    }
    if (key === '/brands') {
      const payload = clone(routes['/brands']);
      payload.items = [...payload.items, ...overlay.extraBrands];
      payload.total = payload.items.length;
      return payload as T;
    }
    const hit = routes[key] ?? routes[key.split('?')[0]];
    if (hit !== undefined) return clone(hit) as T;
    throw new DemoUnavailable(
      'This screen needs the live API — run AdFlow AI locally to use it.',
      'هذي الشاشة تحتاج السيرفر الحقيقي — شغّل النسخة المحلية حتى تستخدمها.',
    );
  }

  // ── Writes (simulated) ─────────────────────────────────────────────
  const suffix = key.startsWith(base) ? key.slice(base.length) : key;

  if (key === '/projects' && method === 'POST') return applyProjectOverlay(routes[base]) as T;
  if (suffix === '' && method === 'PATCH') return applyProjectOverlay(routes[base]) as T;
  if (suffix.startsWith('/duplicate')) return applyProjectOverlay(routes[base]) as T;

  if (suffix === '/analysis/run') return route('/analysis') as T;
  if (suffix.endsWith('/approve')) {
    const entity = suffix.split('/')[1] === 'qc' ? 'final' : suffix.split('/')[1].replace('production', 'production_plan');
    overlay.approvals[entity] = 'approved';
    overlay.state = stageAfter(entity);
    return { ok: true, state: overlay.state } as T;
  }
  if (suffix.startsWith('/concepts/generate')) return route('/concepts') as T;
  if (suffix === '/concepts/select') {
    overlay.selectedConceptId = body?.id ?? null;
    const payload = route('/concepts');
    return (payload.items.find((c: any) => c.id === body?.id) ?? payload.items[0]) as T;
  }
  if (/^\/concepts\/[^/]+\/refine$/.test(suffix)) {
    const payload = route('/concepts');
    const id = suffix.split('/')[2];
    const concept = payload.items.find((c: any) => c.id === id) ?? payload.items[0];
    concept.hook = `هسه ${concept.hook}`;
    concept.version += 1;
    return concept as T;
  }
  if (suffix.startsWith('/script/generate')) return route('/script') as T;
  if (suffix === '/script/select') {
    overlay.selectedScriptId = body?.id ?? null;
    const payload = route('/script');
    return (payload.variants.find((s: any) => s.id === body?.id) ?? payload.variants[0]) as T;
  }
  if (/^\/script\/[^/]+\/refine$/.test(suffix) || /^\/script\/[^/]+$/.test(suffix)) {
    const payload = route('/script');
    const script = payload.variants.find((s: any) => s.variant === 'primary') ?? payload.variants[0];
    script.version += 1;
    return script as T;
  }
  if (suffix === '/voice/preview') {
    const voice = route('/voice');
    return {
      ok: true,
      url: voice.profiles?.[0]?.sample_url ?? null,
      provider: 'mock',
      is_mock: true,
      duration_sec: 3.4,
      estimated_cost_usd: 0.02,
      error: null,
    } as T;
  }
  if (suffix === '/voice/select') {
    overlay.voiceProfileId = body?.voice_profile_id ?? null;
    overlay.voiceLocked = Boolean(body?.lock) || overlay.voiceLocked;
    const voice = route('/voice');
    const profile = voice.profiles.find((p: any) => p.id === body?.voice_profile_id) ?? voice.profiles[0];
    return { ok: true, profile, voice_locked: overlay.voiceLocked } as T;
  }
  if (suffix.startsWith('/storyboard/generate')) return route('/storyboard') as T;
  if (suffix.startsWith('/scenes/')) {
    const payload = route('/storyboard');
    const id = suffix.split('/')[2];
    const scene = payload.storyboard.scenes.find((s: any) => s.id === id) ?? payload.storyboard.scenes[0];
    if (suffix.endsWith('/cheaper')) {
      scene.production_method = 'original_photo';
      scene.estimated_cost_usd = 0;
    }
    if (suffix.endsWith('/premium')) {
      scene.production_method = 'ai_video';
      scene.estimated_cost_usd = 0.55;
    }
    if (suffix.endsWith('/lock')) scene.locked = Boolean(body?.locked);
    if (method === 'PATCH') Object.assign(scene, body?.changes ?? {});
    return scene as T;
  }
  if (suffix === '/production/start') {
    overlay.state = 'GENERATING';
    return { ok: true, jobs_created: route('/production/status').jobs.length, status: route('/production/status') } as T;
  }
  if (suffix === '/production/status') return route('/production/status') as T;
  if (suffix === '/production/finish') {
    overlay.state = 'EDITING';
    return { ok: true, state: overlay.state } as T;
  }
  if (suffix === '/edit/settings') {
    overlay.editSettings = { ...overlay.editSettings, ...(body?.changes ?? {}) };
    if (body?.changes?.editing_style) overlay.editingStyle = body.changes.editing_style;
    const payload = route('/edit');
    payload.settings = { ...payload.settings, ...overlay.editSettings };
    if (overlay.editingStyle) payload.editing_style = overlay.editingStyle;
    return payload as T;
  }
  if (suffix === '/edit/render') return route('/edit').render as T;
  if (suffix === '/qc/run') return route('/qc').report as T;
  if (suffix === '/qc/auto-fix') {
    const report = route('/qc').report;
    return { applied: ['rerender_captions_only'], report_id: report.id, total_score: report.total_score, verdict: report.verdict } as T;
  }
  if (suffix === '/export' && method === 'POST') {
    const payload = route('/export');
    const variant = body?.variant ?? 'master';
    const wantsImage = variant === 'thumbnail';
    const template =
      payload.items.find((item: any) => (wantsImage ? !item.filename.endsWith('.mp4') : item.filename.endsWith('.mp4'))) ??
      payload.items[0];
    const stem = template.filename.replace(/(_[a-z_]+)?\.(mp4|png|svg)$/, '');
    const item = {
      ...template,
      id: `demo-${Date.now()}`,
      variant,
      filename: `${stem}${variant === 'master' ? '' : `_${variant}`}.${wantsImage ? 'png' : 'mp4'}`,
      created_at: new Date().toISOString(),
    };
    overlay.extraExports = [item, ...overlay.extraExports];
    overlay.state = 'EXPORTED';
    return item as T;
  }

  // Media library / brand kit writes
  if (key.startsWith('/assets/upload')) {
    throw new DemoUnavailable(
      'Uploading is disabled in the demo — run AdFlow AI locally to analyse your own media.',
      'الرفع معطّل بوضع العرض — شغّل النسخة المحلية حتى تحلّل موادك.',
    );
  }
  if (key === '/brands' && method === 'POST') {
    const kit = { ...(body ?? {}), id: `demo-brand-${Date.now()}`, created_at: new Date().toISOString() };
    overlay.extraBrands = [...overlay.extraBrands, kit];
    return kit as T;
  }
  if (key.startsWith('/brands/') && method === 'PATCH') return { ...(body ?? {}), id: key.split('/')[2] } as T;
  if (key.startsWith('/brands/') && method === 'DELETE') {
    overlay.extraBrands = overlay.extraBrands.filter((kit) => kit.id !== key.split('/')[2]);
    return { ok: true } as T;
  }

  return { ok: true } as T;
}
