/** Shared API types (mirrors the FastAPI payloads). */

export type Option = { value: string; label_en: string; label_ar: string };

export type ProjectState =
  | 'DRAFT' | 'ANALYZING' | 'ANALYSIS_READY' | 'CONCEPT_REVIEW' | 'CONCEPT_APPROVED'
  | 'SCRIPT_REVIEW' | 'SCRIPT_APPROVED' | 'STORYBOARD_REVIEW' | 'STORYBOARD_APPROVED'
  | 'PRODUCTION_READY' | 'GENERATING' | 'EDITING' | 'QC_REVIEW' | 'FINAL_APPROVAL'
  | 'EXPORTED' | 'PAUSED' | 'FAILED' | 'CANCELLED';

export type StageKey =
  | 'brief' | 'analyze' | 'concepts' | 'script' | 'voice'
  | 'storyboard' | 'production' | 'edit' | 'qc' | 'export';

export type ProjectSummary = {
  id: string;
  name: string;
  category: string;
  goal: string;
  platform: string;
  duration_sec: number;
  language: string;
  dialect: string;
  tone: string;
  state: ProjectState;
  stage: StageKey;
  thumbnail_url: string | null;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  budget_limit_usd: number;
  production_mode: string;
  quality_level: string;
  editing_style: string;
  updated_at: string | null;
  created_at: string | null;
  archived: boolean;
};

export type BudgetSnapshot = {
  budget_limit_usd: number;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  reserved_cost_usd: number;
  regeneration_reserve_usd: number;
  remaining_budget_usd: number;
  over_budget: boolean;
  status: 'safe_to_generate' | 'budget_approval_required';
  entries: number;
};

export type ApprovalInfo = { status: string; version: number; approved_at: string | null; entity_id: string | null };

export type ProjectDetail = ProjectSummary & {
  target_audience: string;
  key_information: string;
  cta: string;
  voice_over_enabled: boolean;
  brand_kit_id: string | null;
  selected_concept_id: string | null;
  selected_script_id: string | null;
  selected_voice_profile_id: string | null;
  voice_locked: boolean;
  edit_settings: Record<string, unknown>;
  architecture_fidelity_lock: boolean;
  product_fidelity_lock: boolean;
  state_history: { from: string; to: string; at: string; note: string }[];
  approvals: Record<string, ApprovalInfo>;
  budget: BudgetSnapshot;
  asset_count: number;
  storyboard_id: string | null;
  stages: StageKey[];
};

export type DirectorNote = {
  key: string;
  message_en: string;
  message_ar: string;
  impact: 'high' | 'medium' | 'low';
  action?: Record<string, unknown> | null;
};

export type Analysis = {
  id: string;
  version: number;
  brief_interpretation: Record<string, any>;
  asset_analysis: Record<string, any>;
  creative_strategy: Record<string, any>;
  production_recommendation: Record<string, any>;
  recommended_mode: string;
  recommended_duration_sec: number;
  recommended_angle: string;
  recommended_voice_style: string;
  estimated_cost_usd: number;
  readiness_score: number;
  confidence_score: number;
  director_notes: DirectorNote[];
  created_at: string | null;
};

export type Concept = {
  id: string;
  name: string;
  name_en: string;
  angle: string;
  one_line_idea: string;
  hook: string;
  creative_direction: string;
  recommended_mode: string;
  recommended_voice: string;
  visual_style: string;
  cta_style: string;
  estimated_cost_usd: number;
  why_this_works: string;
  scores: Record<string, number>;
  score_total: number;
  is_recommended: boolean;
  is_selected: boolean;
  is_alternative: boolean;
  version: number;
};

export type ScriptLine = {
  index: number;
  role: 'hook' | 'body' | 'cta';
  voice_line: string;
  on_screen_text: string;
  start: number;
  end: number;
};

export type ScriptVersion = {
  id: string;
  version: number;
  variant: 'primary' | 'more_sales' | 'more_emotional';
  hook: string;
  body: string;
  cta: string;
  voice_over_text: string;
  on_screen_text: { index: number; text: string; start: number; end: number }[];
  lines: ScriptLine[];
  dialect_preset: string;
  total_duration_sec: number;
  word_count: number;
  score: number;
  critic_notes: string[];
  is_selected: boolean;
  concept_id: string | null;
};

export type VoiceProfile = {
  id: string;
  name: string;
  name_ar: string;
  provider: string;
  gender: string;
  dialect: string;
  style: string;
  speed: number;
  energy: number;
  emotion: number;
  sample_url: string | null;
  is_demo: boolean;
};

export type Scene = {
  id: string;
  scene_number: number;
  start_time: number;
  end_time: number;
  duration_sec: number;
  purpose: string;
  voice_line: string;
  visual_source: string;
  selected_asset_id: string | null;
  visual_direction: string;
  camera_direction: string;
  camera_movement: string;
  lighting: string;
  on_screen_text: string;
  text_animation: string;
  music_instruction: string;
  sfx_instruction: string;
  transition: string;
  production_method: string;
  recommended_model: string;
  recommended_provider: string;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  quality_score: number | null;
  quality_breakdown: Record<string, number>;
  status: string;
  locked: boolean;
  is_hook: boolean;
  is_hero: boolean;
  priority: number;
  keyframe_url: string | null;
  keyframe_approved: boolean;
  output_url: string | null;
  thumbnail_url: string | null;
  compiled_prompt: Record<string, any>;
  generation_attempts: number;
  remix_ops: Record<string, any>;
};

export type ProductionPlan = {
  scene_count: number;
  counts: Record<string, number>;
  voice_cost_usd: number;
  video_cost_usd: number;
  image_cost_usd: number;
  photo_motion_cost_usd: number;
  music_cost_usd: number;
  estimated_total_usd: number;
  budget_limit_usd: number;
  regeneration_reserve_usd: number;
  status: 'safe_to_generate' | 'budget_approval_required';
  generation_order: { scene_id: string; scene_number: number; priority: number; reason_ar: string }[];
  director_notes: DirectorNote[];
};

export type Storyboard = {
  id: string;
  version: number;
  script_version_id: string | null;
  total_duration_sec: number;
  estimated_cost_usd: number;
  continuity_report: {
    checks: { key: string; ok: boolean; message_ar: string }[];
    score: number;
    passed: number;
    total: number;
  };
  production_plan: ProductionPlan;
  scenes: Scene[];
  actions: { key: string; label_en: string; label_ar: string }[];
};

export type Job = {
  id: string;
  type: string;
  status: string;
  progress: number;
  label: string;
  scene_id: string | null;
  attempt: number;
  error: string | null;
  actual_cost_usd: number;
};

export type ProductionStatus = {
  state: ProjectState;
  jobs_total: number;
  jobs_completed: number;
  jobs_failed: number;
  progress: number;
  all_done: boolean;
  jobs: Job[];
  scenes: {
    id: string;
    scene_number: number;
    status: string;
    quality_score: number | null;
    output_url: string | null;
    thumbnail_url: string | null;
    locked: boolean;
    production_method: string;
    actual_cost_usd: number;
    attempts: number;
  }[];
};

export type TimelineTrack = {
  type: 'video' | 'voice' | 'music' | 'sfx' | 'captions' | 'brand' | 'cta' | 'end_screen';
  clips?: any[];
  url?: string | null;
  volume?: number;
  template?: any;
  [key: string]: any;
};

export type Render = {
  id: string;
  version: number;
  editing_style: string;
  settings: Record<string, any>;
  timeline: TimelineTrack[];
  url: string | null;
  poster_url: string | null;
  duration_sec: number;
  width: number;
  height: number;
  status: string;
};

export type QCReport = {
  id: string;
  version: number;
  render_id: string | null;
  scores: Record<string, number>;
  weights: Record<string, number>;
  total_score: number;
  verdict: 'approved' | 'review' | 'fix_required';
  critical_issues: { code: string; severity: string; message_ar: string; message_en?: string }[];
  recommendations: { code: string; message_ar: string; impact?: string }[];
  checks: { level: string; label_en: string; label_ar: string; passed: boolean; score: number }[];
  ready_to_export: boolean;
  auto_fix_plan: { code: string; component: string; action: string; label_ar: string }[];
  thresholds: { approve: number; review: number };
};

export type ExportItem = {
  id: string;
  variant: string;
  aspect_ratio: string;
  width: number;
  height: number;
  filename: string;
  url: string | null;
  size_bytes: number;
  codec: string;
  status: string;
  created_at: string | null;
};

export type Asset = {
  id: string;
  kind: string;
  filename: string;
  url: string;
  thumbnail_url: string;
  mime_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration_sec: number | null;
  orientation: string;
  quality_score: number | null;
  hero_potential: number | null;
  usable: boolean;
  category: string | null;
  suggested_use: string | null;
  analysis: Record<string, any>;
  project_id: string | null;
  is_generated: boolean;
  is_project_reference: boolean;
  tags: string[];
  created_at: string | null;
};

export type BrandKit = {
  id: string;
  name: string;
  name_ar: string | null;
  logo_url: string | null;
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  font_arabic: string;
  font_latin: string;
  caption_style: Record<string, any>;
  editing_style: string;
  voice_profile_id: string | null;
  music_profile: Record<string, any>;
  cta_template: Record<string, any>;
  end_screen_template: Record<string, any>;
  phone: string | null;
  website: string | null;
  social_handles: Record<string, any>;
  pronunciation_rules: Record<string, any>;
  forbidden_phrases: string[];
  preferred_phrases: string[];
  is_default: boolean;
  created_at: string | null;
};

export type ProviderStatus = {
  kind: string;
  name: string;
  models: string[];
  is_mock: boolean;
  requires_key: string | null;
  key_present: boolean;
  available: boolean;
  active: boolean;
  notes: string;
};

export type EditingStyleOption = {
  key: string;
  label_en: string;
  label_ar: string;
  cut_pace_sec: number;
  transition: string;
  caption_density: string;
  color_look: string;
  music_energy: number;
};

export type MetaOptions = {
  goals: Option[];
  platforms: Option[];
  languages: Option[];
  dialects: Option[];
  tones: Option[];
  production_modes: Option[];
  quality_levels: Option[];
  angles: Option[];
  editing_styles: EditingStyleOption[];
  caption_templates: { key: string; label_en: string; label_ar: string }[];
  export_variants: { key: string; label_en: string; label_ar: string }[];
  durations: number[];
  categories: Option[];
  states: string[];
  stages: StageKey[];
  dialect_presets: {
    id: string;
    label_ar: string;
    label_en: string;
    tone_rules: string[];
    preferred: string[];
    forbidden: string[];
    openers: string[];
    closers: string[];
    energy: number;
  }[];
};
