export type MatchStatus = 'preliminary_match' | 'check_needed' | 'not_eligible' | 'closed';
export type RuleResult = { field?: string; outcome: 'pass' | 'fail' | 'unknown' | 'not_applicable'; required: boolean; explanation: string; source_ref?: string; children?: RuleResult[] };
export type Profile = {
  business_name: string; legal_form: 'ip' | 'ooo'; region_code: string; industry_code: string;
  employee_count: number; registration_date: string; purpose_code: string;
  tax_debt: 'yes' | 'no' | 'unknown'; revenue: number | null; version: number; updated_at: string;
};
export type Program = {
  id: string; title: string; operator_name: string; purpose_code: string; region_code: string;
  benefit_type: string; amount_text: string | null; deadline: string | null; state: string;
  description: string; version: number; provenance: {
    data_kind: 'synthetic' | 'curated_official'; source_title: string; source_url: string | null;
    checked_at: string | null; refresh_due_at: string | null;
  };
  match: { status: MatchStatus; rules: RuleResult[]; checked_count: number; required_count: number; source_stale: boolean; profile_version: number | null; program_version: number; calculated_at: string };
  documents?: string[];
};
export type Plan = {
  id: string; program_id: string; program_snapshot: Program; due_at: string; status: 'active' | 'completed' | 'cancelled';
  version: number; reminders_enabled: boolean; progress: number; program_changed: boolean;
  items: { id: string; title: string; kind: string; status: 'todo' | 'done'; order: number; due_at: string | null }[];
};
export type Notification = { id: string; type: string; scheduled_at: string; status: string; attempts: number };
export type Dashboard = { profile: Profile | null; recommendations: Program[]; active_plans: number; next_item: { plan_id: string; title: string; due_at: string } | null };
export type Me = { id: string; display_name: string; mode: 'demo' | 'max'; bot_started: boolean };

type Bridge = { initData?: string; ready?: () => void; expand?: () => void; getViewportSize?: () => unknown };
declare global { interface Window { WebApp?: Bridge } }

const API = import.meta.env.VITE_API_URL || '/api/v1';
let token: string | null = null;
let authAttempt: Promise<{ mode: 'demo' | 'max'; startParam: string | null }> | null = null;

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public fieldErrors: Record<string, string> = {}) { super(message); }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(API + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(response.status, payload.error?.code || 'network_error', payload.error?.message || 'Не удалось выполнить запрос', payload.error?.field_errors || {});
  }
  return response.json() as Promise<T>;
}

async function startAuthentication(): Promise<{ mode: 'demo' | 'max'; startParam: string | null }> {
  const raw = window.WebApp?.initData;
  const result = raw
    ? await request<{ token: string; mode: 'max' }>('/auth/max', { method: 'POST', body: JSON.stringify({ init_data: raw }) })
    : await request<{ token: string; mode: 'demo' }>('/auth/demo', { method: 'POST' });
  token = result.token;
  if (raw) {
    window.WebApp?.ready?.();
    window.WebApp?.expand?.();
  }
  return { mode: result.mode, startParam: raw ? new URLSearchParams(raw).get('start_param') : null };
}

export function authenticate() {
  if (!authAttempt) authAttempt = startAuthentication().catch(error => { authAttempt = null; throw error; });
  return authAttempt;
}
export function clearSession() { token = null; authAttempt = null; }
export function makeKey() { return crypto.randomUUID(); }
