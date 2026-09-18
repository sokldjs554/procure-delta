import { staticDemoRequest, staticDocumentUrl } from "./static-demo";
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };
export interface Actor {
  owner_id: string;
  role: "user" | "operator";
  csrf_token: string;
  synthetic_demo: true;
}
export interface Reason {
  code: string;
  field: string;
  message: string;
  evidence: JsonValue[];
}
export interface Eligibility {
  id: string;
  eligible: boolean;
  hard_failures: Reason[];
  warnings: Reason[];
  ruleset_version: string;
}
export interface Ranking {
  id: string;
  recommended: boolean;
  final_score: string;
  features: Record<string, string>;
  explanation: JsonValue;
  as_of: string;
  evaluation_epoch: string;
  ranking_version: string;
}
export interface Opportunity {
  id: string;
  title: string;
  buyer_name: string;
  procurement_type: string | null;
  lifecycle_stage: string | null;
  estimated_amount: string | null;
  currency: string;
  published_at: string | null;
  closes_at: string | null;
  status: string | null;
  current_version_id: string | null;
  eligibility: Eligibility | null;
  ranking: Ranking | null;
  watched: boolean;
  changed_at: string | null;
  decision_status:
    | "profile_required"
    | "missing_version"
    | "documents_pending"
    | "future_version"
    | "ready";
}
export interface Version {
  id: string;
  version_number: number;
  source_record_id: string;
  effective_at: string;
  transition_kind: string;
  created_at: string;
  normalized_json: JsonValue;
}
export interface Link {
  id: string;
  parent_opportunity_id: string;
  child_opportunity_id: string;
  relation_type: string;
  confidence: string;
  link_method: string;
  status: string;
  evidence_json: JsonValue;
  created_at: string;
  retracted_at: string | null;
}
export interface DocumentItem {
  id: string;
  filename: string;
  media_type: string | null;
  sha256: string | null;
  byte_size: number | null;
  download_status: string;
  original_url: string | null;
  parses: {
    id: string;
    parser_kind: string;
    parser_version: string;
    status: string;
    page_count: number | null;
    quality_json: JsonValue;
  }[];
}
export interface Delta {
  id: string;
  from_version_id: string;
  to_version_id: string;
  field_changes_json: JsonValue;
  document_changes_json: JsonValue;
  impact_level: string;
  impact_reasons_json: JsonValue;
  comparison_kind: string;
  created_at: string;
  applicable_now: boolean;
}
export interface Extraction {
  status: string;
  id: string | null;
  extractor_version: string | null;
  schema_version: string | null;
  input_fingerprint: string | null;
  trusted_fields: JsonValue;
  evidence: JsonValue;
  conflicts: JsonValue;
  validation_errors: string[];
}
export interface OpportunityDetail extends Opportunity {
  versions: Version[];
  timeline: {
    opportunity_ids: string[];
    active_links: Link[];
    historical_links: Link[];
  };
  deltas: { items: Delta[]; current_inputs_ready: boolean };
  documents: DocumentItem[];
  extraction: Extraction;
}
export interface Profile {
  id: string;
  owner_user_id: string;
  display_name: string;
  synthetic_demo: true;
  regions: string[];
  industries: string[];
  capabilities: string[];
  certifications: string[];
  employee_band: string | null;
  min_contract_amount: string | null;
  max_contract_amount: string | null;
  contract_currency: string | null;
  excluded_keywords: string[];
}
export type ProfileWrite = Omit<Profile, "id" | "owner_user_id">;
export interface Preferences {
  enabled: boolean;
  channels: ("local" | "webhook" | "email")[];
  triggers: (
    | "new_high_relevance"
    | "watched_material_change"
    | "deadline_changed"
    | "eligibility_changed"
    | "outcome_published"
  )[];
}
export interface NotificationItem {
  id: string;
  opportunity_id: string;
  delta_id: string | null;
  channel: string;
  template_key: string;
  status: string;
  attempt_count: number;
  next_attempt_at: string | null;
  sent_at: string | null;
  payload: JsonValue;
  receipt_id: string | null;
  received_at: string | null;
}
export interface Activity {
  completed: number;
  failed: number;
  retried: number;
  ongoing: number;
}
export interface GroupCount {
  kind: string;
  status: string;
  count: number;
}
export interface AdminPipeline {
  observed_at: string;
  records_fetched_today: number;
  new_records_today: number;
  changed_versions_today: number;
  duplicates_skipped_today: number;
  parsing_failures: number;
  ocr_fallbacks: number;
  structured_extraction_count: number;
  schema_validation_failures: number;
  retry_queue_count: number;
  dlq_count: number;
  worker_queue_depth: number;
  scheduler_queue_depth: number;
  worker_heartbeat: boolean;
  scheduler_heartbeat: boolean;
  worker_activity: Activity | null;
  scheduler_activity: Activity | null;
  parsing: GroupCount[];
  extraction: GroupCount[];
}
export interface AdminSource {
  id: string;
  code: string;
  display_name: string;
  enabled: boolean;
  polling_interval_seconds: number;
  last_success_at: string | null;
  last_failure_at: string | null;
}
export interface AdminFailure {
  id: string;
  job_type: string;
  attempts: number;
  error_code: string;
  last_error_at: string;
  dead_lettered: boolean;
  next_retry_at: string | null;
}
export interface Release {
  name: string;
  version: string;
  revision: string;
  authentication: string;
  extraction_mode: string;
}

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const STATIC_DEMO = process.env.NEXT_PUBLIC_STATIC_DEMO === "true";
let csrfToken = "";
let bootstrapPromise: Promise<Actor> | null = null;
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
async function request<T>(path: string, init: RequestInit = {}) {
  if (STATIC_DEMO) return staticDemoRequest<T>(path, init);
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (csrfToken && init.method && init.method !== "GET")
    headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`${API}/api/v1${path}`, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok)
    throw new ApiError(
      response.status,
      response.status === 401
        ? "데모 세션이 필요합니다."
        : `요청을 완료하지 못했습니다 (${response.status})`,
    );
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export async function session() {
  const actor = await request<Actor>("/auth/session");
  csrfToken = actor.csrf_token;
  return actor;
}
export async function login() {
  const actor = await request<Actor>("/auth/demo-login", {
    method: "POST",
    body: "{}",
  });
  csrfToken = actor.csrf_token;
  return actor;
}
export async function operatorLogin(operatorSecret: string) {
  const actor = await request<Actor>("/auth/demo-login", {
    method: "POST",
    body: JSON.stringify({ operator_secret: operatorSecret }),
  });
  csrfToken = actor.csrf_token;
  bootstrapPromise = null;
  return actor;
}
export function bootstrapSession() {
  if (!bootstrapPromise)
    bootstrapPromise = session()
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) return login();
        throw error;
      })
      .catch((error) => {
        bootstrapPromise = null;
        throw error;
      });
  return bootstrapPromise;
}
export async function logout() {
  await request<void>("/auth/logout", { method: "POST" });
  csrfToken = "";
  bootstrapPromise = null;
}
export function getProfile() {
  return request<Profile>("/company-profile");
}
export function updateProfile(body: Partial<ProfileWrite>) {
  return request<Profile>("/company-profile", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}
export function getOpportunities(query = "") {
  return request<{ items: Opportunity[]; next_cursor: string | null }>(
    `/opportunities${query ? `?${query}` : ""}`,
  );
}
export function getOpportunity(id: string) {
  return request<OpportunityDetail>(`/opportunities/${id}`);
}
export function getWatchlist(cursor?: string) {
  return request<{ items: Opportunity[]; next_cursor: string | null }>(
    `/watchlist${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
}
export function setWatch(id: string, watched: boolean) {
  return request(`/opportunities/${id}/watch`, {
    method: watched ? "POST" : "DELETE",
  });
}
export function getNotifications(cursor?: string) {
  return request<{ items: NotificationItem[]; next_cursor: string | null }>(
    `/notifications${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
}
export function getPreferences() {
  return request<Preferences>("/notifications/preferences");
}
export function setPreferences(body: Preferences) {
  return request<Preferences>("/notifications/preferences", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
export const documentUrl = (id: string) =>
  STATIC_DEMO ? staticDocumentUrl(id) : `${API}/api/v1/documents/${id}/original`;
export function getAdminPipeline() {
  return request<AdminPipeline>("/admin/pipeline");
}
export function getAdminSources() {
  return request<AdminSource[]>("/admin/sources");
}
export function getAdminFailures(cursor?: string) {
  return request<{ items: AdminFailure[]; next_cursor: string | null }>(
    `/admin/failures${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
}
export function getRelease() {
  return request<Release>("/release");
}
export function retryAdminFailure(id: string) {
  return request<{
    failure_id: string;
    status: string;
    queue_published: boolean;
  }>(`/admin/failures/${id}/retry`, { method: "POST" });
}

export interface EvaluationSummary {
  status: "measured" | "not_run";
  synthetic: boolean;
  public_real_records: number;
  measured_at: string | null;
  dataset_version: string | null;
  dataset_sha256: string | null;
  source_sha256: string | null;
  extraction_accuracy: number | null;
  extraction_correct: number;
  extraction_support: number;
  delta_precision: number | null;
  delta_recall: number | null;
  delta_support: number;
  lifecycle_precision: number | null;
  lifecycle_resolved: number;
  lifecycle_cases: number;
  replay_queries: number;
  ocr_accuracy: number | null;
  ocr_correct: number;
  ocr_support: number;
  ocr_language: string | null;
  hosted_evaluated: boolean;
  notice: string;
}
export function getEvaluationSummary() {
  return request<EvaluationSummary>("/evaluation/summary");
}