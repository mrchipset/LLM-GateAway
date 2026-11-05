import {
  isUnsafeMethod,
  readCsrfToken,
  reportUnauthorized,
  type AdminActorType,
  type AdminRole,
  type AdminSession,
} from '../lib/session';
import { withTimeout } from '../lib/timeout';

export type { AdminActorType, AdminRole, AdminSession } from '../lib/session';

export interface HealthResponse {
  status: 'ok';
  version: string;
}

export interface ReadinessResponse {
  status: 'ok' | 'unavailable';
  checks: Record<string, string>;
}

export interface ModelSummary {
  id: string;
  provider: string;
  upstream_model: string;
  enabled: boolean;
  created_at: string;
  requests_per_minute?: number | null;
  tokens_per_minute?: number | null;
  context_window?: number | null;
  max_output_tokens?: number | null;
  supports_tools?: boolean;
  supports_streaming?: boolean;
}

export interface ModelListResponse {
  items: ModelSummary[];
  total: number;
  limit: number;
  offset: number;
}

export type ModelProvider = 'openai' | 'deepseek' | 'azure' | 'anthropic' | 'fake';

export interface CreateModelInput {
  id: string;
  provider: ModelProvider;
  upstream_model: string;
  enabled: boolean;
  requests_per_minute?: number;
  tokens_per_minute?: number;
  context_window?: number;
  max_output_tokens?: number;
  supports_tools?: boolean;
  supports_streaming?: boolean;
}

/** Only the fields present in the patch are sent; `null` clears a limit. */
export interface UpdateModelInput {
  enabled?: boolean;
  provider?: ModelProvider;
  upstream_model?: string;
  requests_per_minute?: number | null;
  tokens_per_minute?: number | null;
}

export interface ModelDeployment {
  id: string;
  model_id: string;
  name: string;
  provider: string;
  upstream_model: string;
  weight: number;
  enabled: boolean;
  credential_env: string | null;
  base_url: string | null;
  created_at: string;
}

export interface DeploymentListResponse {
  model_id: string;
  items: ModelDeployment[];
}

export interface CreateDeploymentInput {
  name: string;
  provider: ModelProvider;
  upstream_model: string;
  weight: number;
  enabled: boolean;
  credential_env?: string;
  base_url?: string;
}

export interface UpdateDeploymentInput {
  upstream_model?: string;
  weight?: number;
  enabled?: boolean;
  credential_env?: string | null;
  base_url?: string | null;
}

export type ModelAccessMode = 'all' | 'allowlist';

export interface TenantModelAccess {
  tenant_id: string;
  mode: ModelAccessMode;
  model_ids: string[];
}

export interface TenantModelAccessInput {
  mode: ModelAccessMode;
  model_ids: string[];
}

export interface TenantSummary {
  id: string;
  name: string;
  created_at: string;
  monthly_token_quota: number | null;
  requests_per_minute: number | null;
  tokens_per_minute?: number | null;
  max_concurrent_requests?: number | null;
  audit_retention_days?: number | null;
  audit_enabled: boolean;
  model_access_mode: ModelAccessMode;
  plan_tokens: number | null;
  plan_allow_overage: boolean;
  monthly_cost_budget: string | null;
}

export interface TenantListResponse {
  items: TenantSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface TenantPageOptions {
  limit?: number;
  offset?: number;
}

export interface ApiKeySummary {
  id: string;
  tenant_id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  requests_per_minute?: number | null;
  tokens_per_minute?: number | null;
  max_concurrent_requests?: number | null;
}

export interface ApiKeyListResponse {
  items: ApiKeySummary[];
  total: number;
  limit: number;
  offset: number;
  tenant_id: string | null;
}

export interface ApiKeyPageOptions {
  tenantId?: string | null;
  limit?: number;
  offset?: number;
}

export interface CreatedApiKey {
  id: string;
  tenant_id: string;
  name: string;
  key: string;
  key_prefix: string;
  created_at: string;
  expires_at: string | null;
  requests_per_minute?: number | null;
  tokens_per_minute?: number | null;
  max_concurrent_requests?: number | null;
}

export interface CreateApiKeyInput {
  name: string;
  tenant_id: string;
  expires_at?: string;
  requests_per_minute?: number;
  tokens_per_minute?: number;
  max_concurrent_requests?: number;
}

/** Only the fields present in the patch are sent; `null` clears a limit. */
export interface ApiKeyLimitsPatch {
  requests_per_minute?: number | null;
  tokens_per_minute?: number | null;
  max_concurrent_requests?: number | null;
}

export interface CreateTenantInput {
  name: string;
  audit_enabled?: boolean;
  tokens_per_minute?: number;
  max_concurrent_requests?: number;
  audit_retention_days?: number;
}

export interface TenantLimitsPatch {
  monthly_token_quota?: number | null;
  requests_per_minute?: number | null;
  tokens_per_minute?: number | null;
  max_concurrent_requests?: number | null;
  audit_retention_days?: number | null;
  audit_enabled?: boolean;
  plan_tokens?: number | null;
  plan_allow_overage?: boolean;
  monthly_cost_budget?: string | null;
}

export interface ModelPrice {
  id: string;
  model_id: string;
  input_per_million: string;
  cached_input_per_million: string | null;
  output_per_million: string;
  currency: string;
  effective_from: string;
  created_at: string;
}

export interface ModelPriceListResponse {
  items: ModelPrice[];
  total: number;
  limit: number;
  offset: number;
}

export interface CreateModelPriceInput {
  input_per_million: string;
  cached_input_per_million?: string;
  output_per_million: string;
  effective_from?: string;
}

export interface TenantBillingSummary {
  tenant_id: string;
  currency: string;
  period_start: string;
  period_end: string;
  plan_tokens: number | null;
  plan_allow_overage: boolean;
  monthly_cost_budget: string | null;
  used_tokens: number;
  covered_tokens: number;
  billable_tokens: number;
  requests: number;
  list_cost: string;
  billed_cost: string;
  budget_remaining: string | null;
}

export type AuditChangeType =
  'new_session' | 'continuation' | 'regeneration' | 'edit' | 'truncation';

export type AuditStatus =
  'completed' | 'upstream_error' | 'client_error' | 'client_disconnected' | 'error';

export type AuditMatchMethod = 'explicit' | 'prefix' | 'new';

export type AuditMessagePayload = Record<string, unknown>;
export type AuditParams = Record<string, unknown>;

export interface AuditSessionSummary {
  id: string;
  tenant_id: string;
  external_session_id: string | null;
  api_key_id: string;
  api_key_prefix: string;
  model_id: string;
  provider: string;
  title_preview: string;
  created_at: string;
  last_seen_at: string;
  request_count: number;
  total_tokens: number;
}

export interface AuditSessionPage {
  items: AuditSessionSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditMessageRef {
  index: number;
  role: string;
  hash: string;
  preview: string;
}

export interface AuditMessageModification {
  index: number;
  role: string;
  before_hash: string;
  after_hash: string;
  before_preview: string;
  after_preview: string;
}

export type AuditParameterChange =
  | { kind: 'values'; from: unknown; to: unknown }
  | { kind: 'hashes'; from_hash: string | null; to_hash: string | null };

export interface AuditResponseChange {
  content_changed: boolean;
  previous_content_hash: string | null;
  content_hash: string | null;
  finish_reason_changed: boolean;
  previous_finish_reason: string | null;
  finish_reason: string | null;
  tool_calls_added: number;
  tool_calls_removed: number;
  tool_call_names: string[];
}

export interface AuditDiff {
  change_type: AuditChangeType;
  common_prefix: number;
  added_messages: AuditMessageRef[];
  modified_messages: AuditMessageModification[];
  removed_messages: AuditMessageRef[];
  parameter_changes: Record<string, AuditParameterChange>;
  usage_delta: Record<string, number>;
  response_change: AuditResponseChange;
}

export interface AuditTurn {
  request_id: string;
  parent_request_id: string | null;
  turn_index: number;
  match_method: AuditMatchMethod;
  change_type: AuditChangeType;
  model_id: string;
  provider: string;
  is_stream: boolean;
  status: AuditStatus;
  finish_reason: string | null;
  truncated: boolean;
  created_at: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cached_tokens: number | null;
  total_tokens: number | null;
  request_message_count: number;
  diff: AuditDiff | null;
  request_messages: AuditMessagePayload[] | null;
  request_params: AuditParams | null;
  response_content: string | null;
  response_tool_calls: AuditMessagePayload[] | null;
}

export interface AuditSessionDetailResponse {
  session: AuditSessionSummary;
  turns: AuditTurn[];
}

export interface AuditRequestDetail {
  request_id: string;
  session_id: string;
  tenant_id: string;
  api_key_id: string;
  parent_request_id: string | null;
  turn_index: number;
  match_method: AuditMatchMethod;
  change_type: AuditChangeType;
  model_id: string;
  provider: string;
  is_stream: boolean;
  status: AuditStatus;
  finish_reason: string | null;
  truncated: boolean;
  created_at: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cached_tokens: number | null;
  total_tokens: number | null;
  request_messages: AuditMessagePayload[];
  request_params: AuditParams;
  response_content: string | null;
  response_tool_calls: AuditMessagePayload[] | null;
  response_content_hash: string | null;
}

export interface AuditRequestDetailResponse {
  request: AuditRequestDetail;
  diff: AuditDiff | null;
  truncated: boolean;
}

export interface AuditSessionQuery {
  tenantId: string | null;
  apiKeyId: string | null;
  modelId: string | null;
  q: string | null;
  since: string;
  until?: string | null;
  limit: number;
  offset: number;
}

export type AuditExportFormat = 'jsonl' | 'csv';

export interface AuditExportQuery {
  tenantId: string;
  since: string;
  until: string;
  format: AuditExportFormat;
}

export interface AuditExportFile {
  blob: Blob;
  filename: string;
}

export interface AuditDeleteQuery {
  tenantId: string;
  before: string;
  dryRun?: boolean;
  batchSize?: number;
  maxBatches?: number;
}

export interface AuditDeleteResult {
  tenant_id: string;
  before: string;
  dry_run: boolean;
  requests_deleted: number;
  sessions_deleted: number;
  requests_remaining: number;
}

export interface UsageCosts {
  covered_tokens: number;
  billable_tokens: number;
  list_cost: string;
  billed_cost: string;
}

export interface UsageCounts extends UsageCosts {
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  total_tokens: number;
  requests: number;
}

export interface UsageModelSummary extends UsageCounts {
  model_id: string;
  provider: string;
}

export interface UsageSummaryResponse extends UsageCounts {
  by_model: UsageModelSummary[];
}

export interface UsagePoint extends UsageCounts {
  bucket_start: string;
}

export type UsageBucket = 'hour' | 'day';

export interface UsageSeriesResponse {
  bucket: UsageBucket;
  points: UsagePoint[];
}

export interface KeyUsageSummary extends UsageCounts {
  api_key_id: string;
  name: string | null;
  key_prefix: string | null;
}

export interface UsageByKeyResponse {
  limit: number;
  items: KeyUsageSummary[];
}

export interface UsageWindow {
  tenantId: string | null;
  since: string;
  until?: string;
}

export interface LoginInput {
  username: string;
  password: string;
}

export interface LoginResult {
  username: string;
  display_name: string;
  role: AdminRole;
  actor_type: AdminActorType;
  expires_at: string;
}

export interface AdminSummary {
  id: string;
  username: string;
  display_name: string;
  role: AdminRole;
  active: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}

export interface AdminListResponse {
  items: AdminSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface CreateAdminInput {
  username: string;
  display_name: string;
  role: AdminRole;
  password: string;
}

export interface UpdateAdminInput {
  display_name?: string;
  role?: AdminRole;
  active?: boolean;
  password?: string;
}

export interface AdminAuditEvent {
  id: string;
  actor_type: AdminActorType;
  actor_id: string | null;
  actor_name: string;
  action: string;
  target_type: string;
  target_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  request_id: string | null;
  created_at: string;
}

export interface AdminAuditListResponse {
  items: AdminAuditEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminAuditQuery {
  actorId: string | null;
  action: string | null;
  targetType: string | null;
  targetId: string | null;
  since: string | null;
  until: string | null;
  limit: number;
  offset: number;
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly requestId: string | null;
  readonly errorType: string | null;

  constructor(args: {
    status: number;
    message: string;
    code?: string | null;
    requestId?: string | null;
    errorType?: string | null;
  }) {
    super(args.message);
    this.name = 'ApiRequestError';
    this.status = args.status;
    this.code = args.code ?? null;
    this.requestId = args.requestId ?? null;
    this.errorType = args.errorType ?? null;
  }
}

const REQUEST_TIMEOUT_MS = 10_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return isRecord(value) && Object.values(value).every((entry) => typeof entry === 'string');
}

function isModelSummary(value: unknown): value is ModelSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.provider === 'string' &&
    typeof value.upstream_model === 'string' &&
    typeof value.enabled === 'boolean' &&
    typeof value.created_at === 'string' &&
    isOptionalPositiveInt(value.requests_per_minute) &&
    isOptionalPositiveInt(value.tokens_per_minute) &&
    isOptionalPositiveInt(value.context_window) &&
    isOptionalPositiveInt(value.max_output_tokens) &&
    isOptionalBoolean(value.supports_tools) &&
    isOptionalBoolean(value.supports_streaming)
  );
}

function isDeployment(value: unknown): value is ModelDeployment {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.model_id === 'string' &&
    typeof value.name === 'string' &&
    typeof value.provider === 'string' &&
    typeof value.upstream_model === 'string' &&
    typeof value.weight === 'number' &&
    Number.isInteger(value.weight) &&
    value.weight >= 1 &&
    value.weight <= 100 &&
    typeof value.enabled === 'boolean' &&
    isNullableString(value.credential_env) &&
    isNullableString(value.base_url) &&
    typeof value.created_at === 'string'
  );
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isNullableCount(value: unknown): value is number | null {
  return value === null || isCount(value);
}

function isPositiveCount(value: unknown): value is number {
  return isCount(value) && value >= 1;
}

/** Older backends may omit limit fields; treat an absent field as "not set". */
function isOptionalPositiveInt(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || isPositiveCount(value);
}

/** Older backends may omit capability flags; the caller supplies the default. */
function isOptionalBoolean(value: unknown): value is boolean | undefined {
  return value === undefined || typeof value === 'boolean';
}

function isOptionalNullableCount(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || isCount(value);
}

function isDecimalString(value: unknown): value is string {
  return typeof value === 'string' && /^\d+(\.\d+)?$/.test(value);
}

function isModelPrice(value: unknown): value is ModelPrice {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.model_id === 'string' &&
    isDecimalString(value.input_per_million) &&
    (value.cached_input_per_million === null || isDecimalString(value.cached_input_per_million)) &&
    isDecimalString(value.output_per_million) &&
    typeof value.currency === 'string' &&
    typeof value.effective_from === 'string' &&
    typeof value.created_at === 'string'
  );
}

function isTenantBillingSummary(value: unknown): value is TenantBillingSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.tenant_id === 'string' &&
    typeof value.currency === 'string' &&
    typeof value.period_start === 'string' &&
    typeof value.period_end === 'string' &&
    isNullableCount(value.plan_tokens) &&
    typeof value.plan_allow_overage === 'boolean' &&
    (value.monthly_cost_budget === null || isDecimalString(value.monthly_cost_budget)) &&
    isCount(value.used_tokens) &&
    isCount(value.covered_tokens) &&
    isCount(value.billable_tokens) &&
    isCount(value.requests) &&
    isDecimalString(value.list_cost) &&
    isDecimalString(value.billed_cost) &&
    (value.budget_remaining === null || isDecimalString(value.budget_remaining))
  );
}

function isTenantSummary(value: unknown): value is TenantSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.name === 'string' &&
    typeof value.created_at === 'string' &&
    isNullableCount(value.monthly_token_quota) &&
    isNullableCount(value.requests_per_minute) &&
    isOptionalPositiveInt(value.tokens_per_minute) &&
    isOptionalPositiveInt(value.max_concurrent_requests) &&
    isOptionalNullableCount(value.audit_retention_days) &&
    typeof value.audit_enabled === 'boolean' &&
    isModelAccessMode(value.model_access_mode) &&
    isNullableCount(value.plan_tokens) &&
    typeof value.plan_allow_overage === 'boolean' &&
    (value.monthly_cost_budget === null || isDecimalString(value.monthly_cost_budget))
  );
}

function isModelAccessMode(value: unknown): value is ModelAccessMode {
  return value === 'all' || value === 'allowlist';
}

function isTenantModelAccess(value: unknown): value is TenantModelAccess {
  if (!isRecord(value)) return false;
  return (
    typeof value.tenant_id === 'string' &&
    isModelAccessMode(value.mode) &&
    Array.isArray(value.model_ids) &&
    value.model_ids.every((modelId) => typeof modelId === 'string')
  );
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isApiKeySummary(value: unknown): value is ApiKeySummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.tenant_id === 'string' &&
    typeof value.name === 'string' &&
    typeof value.key_prefix === 'string' &&
    typeof value.created_at === 'string' &&
    isNullableString(value.expires_at) &&
    isNullableString(value.revoked_at) &&
    isNullableString(value.last_used_at) &&
    isOptionalPositiveInt(value.requests_per_minute) &&
    isOptionalPositiveInt(value.tokens_per_minute) &&
    isOptionalPositiveInt(value.max_concurrent_requests)
  );
}

function isCreatedApiKey(value: unknown): value is CreatedApiKey {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.tenant_id === 'string' &&
    typeof value.name === 'string' &&
    typeof value.key === 'string' &&
    typeof value.key_prefix === 'string' &&
    typeof value.created_at === 'string' &&
    isNullableString(value.expires_at) &&
    isOptionalPositiveInt(value.requests_per_minute) &&
    isOptionalPositiveInt(value.tokens_per_minute) &&
    isOptionalPositiveInt(value.max_concurrent_requests)
  );
}

function isUsageCounts(value: unknown): value is UsageCounts {
  if (!isRecord(value)) return false;
  const {
    prompt_tokens,
    completion_tokens,
    cached_tokens,
    total_tokens,
    requests,
    covered_tokens,
    billable_tokens,
    list_cost,
    billed_cost,
  } = value;
  return (
    isCount(prompt_tokens) &&
    isCount(completion_tokens) &&
    isCount(cached_tokens) &&
    isCount(total_tokens) &&
    isCount(requests) &&
    isCount(covered_tokens) &&
    isCount(billable_tokens) &&
    isDecimalString(list_cost) &&
    isDecimalString(billed_cost)
  );
}

function isUsageModelSummary(value: unknown): value is UsageModelSummary {
  if (!isRecord(value) || !isUsageCounts(value)) return false;
  return typeof value.model_id === 'string' && typeof value.provider === 'string';
}

function isUsagePoint(value: unknown): value is UsagePoint {
  if (!isRecord(value) || !isUsageCounts(value)) return false;
  return typeof value.bucket_start === 'string';
}

function isUsageBucket(value: unknown): value is UsageBucket {
  return value === 'hour' || value === 'day';
}

function isKeyUsageSummary(value: unknown): value is KeyUsageSummary {
  if (!isRecord(value) || !isUsageCounts(value)) return false;
  return (
    typeof value.api_key_id === 'string' &&
    (value.name === null || typeof value.name === 'string') &&
    (value.key_prefix === null || typeof value.key_prefix === 'string')
  );
}

function isAuditChangeType(value: unknown): value is AuditChangeType {
  return (
    value === 'new_session' ||
    value === 'continuation' ||
    value === 'regeneration' ||
    value === 'edit' ||
    value === 'truncation'
  );
}

function isAuditStatus(value: unknown): value is AuditStatus {
  return (
    value === 'completed' ||
    value === 'upstream_error' ||
    value === 'client_error' ||
    value === 'client_disconnected' ||
    value === 'error'
  );
}

function isAuditMatchMethod(value: unknown): value is AuditMatchMethod {
  return value === 'explicit' || value === 'prefix' || value === 'new';
}

function isNullableInteger(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isInteger(value));
}

function isAuditSessionSummary(value: unknown): value is AuditSessionSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.tenant_id === 'string' &&
    isNullableString(value.external_session_id) &&
    typeof value.api_key_id === 'string' &&
    typeof value.api_key_prefix === 'string' &&
    typeof value.model_id === 'string' &&
    typeof value.provider === 'string' &&
    typeof value.title_preview === 'string' &&
    typeof value.created_at === 'string' &&
    typeof value.last_seen_at === 'string' &&
    isCount(value.request_count) &&
    isCount(value.total_tokens)
  );
}

function isAuditDeleteResult(value: unknown): value is AuditDeleteResult {
  if (!isRecord(value)) return false;
  return (
    typeof value.tenant_id === 'string' &&
    typeof value.before === 'string' &&
    typeof value.dry_run === 'boolean' &&
    isCount(value.requests_deleted) &&
    isCount(value.sessions_deleted) &&
    isCount(value.requests_remaining)
  );
}

function isAuditMessageRef(value: unknown): value is AuditMessageRef {
  if (!isRecord(value)) return false;
  return (
    isCount(value.index) &&
    typeof value.role === 'string' &&
    typeof value.hash === 'string' &&
    typeof value.preview === 'string'
  );
}

function isAuditMessageModification(value: unknown): value is AuditMessageModification {
  if (!isRecord(value)) return false;
  return (
    isCount(value.index) &&
    typeof value.role === 'string' &&
    typeof value.before_hash === 'string' &&
    typeof value.after_hash === 'string' &&
    typeof value.before_preview === 'string' &&
    typeof value.after_preview === 'string'
  );
}

function parseAuditParameterChange(value: unknown): AuditParameterChange | null {
  if (!isRecord(value)) return null;
  if ('from_hash' in value || 'to_hash' in value || value.truncated === true) {
    const fromHash = value.from_hash;
    const toHash = value.to_hash;
    if (fromHash !== undefined && fromHash !== null && typeof fromHash !== 'string') return null;
    if (toHash !== undefined && toHash !== null && typeof toHash !== 'string') return null;
    return {
      kind: 'hashes',
      from_hash: typeof fromHash === 'string' ? fromHash : null,
      to_hash: typeof toHash === 'string' ? toHash : null,
    };
  }
  if ('from' in value || 'to' in value) {
    return { kind: 'values', from: value.from, to: value.to };
  }
  return null;
}

function isAuditResponseChange(value: unknown): value is AuditResponseChange {
  if (!isRecord(value)) return false;
  return (
    typeof value.content_changed === 'boolean' &&
    isNullableString(value.previous_content_hash) &&
    isNullableString(value.content_hash) &&
    typeof value.finish_reason_changed === 'boolean' &&
    isNullableString(value.previous_finish_reason) &&
    isNullableString(value.finish_reason) &&
    isCount(value.tool_calls_added) &&
    isCount(value.tool_calls_removed) &&
    Array.isArray(value.tool_call_names) &&
    value.tool_call_names.every((name) => typeof name === 'string')
  );
}

function parseAuditDiff(value: unknown): AuditDiff | null {
  if (!isRecord(value)) return null;
  if (!isRecord(value.parameter_changes) || !isRecord(value.usage_delta)) return null;
  if (!isAuditChangeType(value.change_type)) return null;
  if (!isCount(value.common_prefix)) return null;
  if (!Array.isArray(value.added_messages) || !value.added_messages.every(isAuditMessageRef)) {
    return null;
  }
  if (
    !Array.isArray(value.modified_messages) ||
    !value.modified_messages.every(isAuditMessageModification)
  ) {
    return null;
  }
  if (!Array.isArray(value.removed_messages) || !value.removed_messages.every(isAuditMessageRef)) {
    return null;
  }
  if (Object.values(value.usage_delta).some((delta) => !Number.isInteger(delta))) return null;
  if (!isAuditResponseChange(value.response_change)) return null;

  const parameterChanges: Record<string, AuditParameterChange> = {};
  for (const [field, change] of Object.entries(value.parameter_changes)) {
    const parsed = parseAuditParameterChange(change);
    if (parsed === null) return null;
    parameterChanges[field] = parsed;
  }

  return {
    change_type: value.change_type,
    common_prefix: value.common_prefix,
    added_messages: value.added_messages,
    modified_messages: value.modified_messages,
    removed_messages: value.removed_messages,
    parameter_changes: parameterChanges,
    usage_delta: value.usage_delta as Record<string, number>,
    response_change: value.response_change,
  };
}

function isAuditMessagePayload(value: unknown): value is AuditMessagePayload {
  return isRecord(value);
}

function parseNullableMessagePayloads(value: unknown): AuditMessagePayload[] | null {
  if (value === null || value === undefined) return null;
  if (!Array.isArray(value) || !value.every(isAuditMessagePayload)) return null;
  return value;
}

function parseNullableParams(value: unknown): AuditParams | null {
  if (value === null || value === undefined) return null;
  return isRecord(value) ? value : null;
}

function parseNullableContent(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return typeof value === 'string' ? value : null;
}

function parseAuditTurn(value: unknown): AuditTurn | null {
  if (!isRecord(value)) return null;
  if (typeof value.request_id !== 'string') return null;
  if (value.parent_request_id !== null && typeof value.parent_request_id !== 'string') return null;
  if (!isCount(value.turn_index)) return null;
  if (!isAuditMatchMethod(value.match_method) || !isAuditChangeType(value.change_type)) return null;
  if (typeof value.model_id !== 'string' || typeof value.provider !== 'string') return null;
  if (typeof value.is_stream !== 'boolean' || !isAuditStatus(value.status)) return null;
  if (value.finish_reason !== null && typeof value.finish_reason !== 'string') return null;
  if (typeof value.truncated !== 'boolean' || typeof value.created_at !== 'string') return null;
  if (
    !isNullableInteger(value.prompt_tokens) ||
    !isNullableInteger(value.completion_tokens) ||
    !isNullableInteger(value.cached_tokens) ||
    !isNullableInteger(value.total_tokens)
  ) {
    return null;
  }
  if (!isCount(value.request_message_count)) return null;

  const diff = value.diff === null ? null : parseAuditDiff(value.diff);
  if (value.diff !== null && diff === null) return null;

  const requestMessages =
    value.request_messages === null || value.request_messages === undefined
      ? null
      : parseNullableMessagePayloads(value.request_messages);
  if (
    value.request_messages !== null &&
    value.request_messages !== undefined &&
    requestMessages === null
  ) {
    return null;
  }

  const requestParams =
    value.request_params === null || value.request_params === undefined
      ? null
      : parseNullableParams(value.request_params);
  if (
    value.request_params !== null &&
    value.request_params !== undefined &&
    requestParams === null
  ) {
    return null;
  }

  const responseContent = parseNullableContent(value.response_content);
  if (
    value.response_content !== null &&
    value.response_content !== undefined &&
    responseContent === null
  ) {
    return null;
  }

  const responseToolCalls = parseNullableMessagePayloads(value.response_tool_calls);
  if (
    value.response_tool_calls !== null &&
    value.response_tool_calls !== undefined &&
    responseToolCalls === null
  ) {
    return null;
  }

  return {
    request_id: value.request_id,
    parent_request_id: value.parent_request_id,
    turn_index: value.turn_index,
    match_method: value.match_method,
    change_type: value.change_type,
    model_id: value.model_id,
    provider: value.provider,
    is_stream: value.is_stream,
    status: value.status,
    finish_reason: value.finish_reason,
    truncated: value.truncated,
    created_at: value.created_at,
    prompt_tokens: value.prompt_tokens,
    completion_tokens: value.completion_tokens,
    cached_tokens: value.cached_tokens,
    total_tokens: value.total_tokens,
    request_message_count: value.request_message_count,
    diff,
    request_messages: requestMessages,
    request_params: requestParams,
    response_content: responseContent,
    response_tool_calls: responseToolCalls,
  };
}

function parseAuditRequestDetail(value: unknown): AuditRequestDetail | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.request_id !== 'string' ||
    typeof value.session_id !== 'string' ||
    typeof value.tenant_id !== 'string' ||
    typeof value.api_key_id !== 'string'
  ) {
    return null;
  }
  if (value.parent_request_id !== null && typeof value.parent_request_id !== 'string') return null;
  if (!isCount(value.turn_index)) return null;
  if (!isAuditMatchMethod(value.match_method) || !isAuditChangeType(value.change_type)) return null;
  if (typeof value.model_id !== 'string' || typeof value.provider !== 'string') return null;
  if (typeof value.is_stream !== 'boolean' || !isAuditStatus(value.status)) return null;
  if (value.finish_reason !== null && typeof value.finish_reason !== 'string') return null;
  if (typeof value.truncated !== 'boolean' || typeof value.created_at !== 'string') return null;
  if (
    !isNullableInteger(value.prompt_tokens) ||
    !isNullableInteger(value.completion_tokens) ||
    !isNullableInteger(value.cached_tokens) ||
    !isNullableInteger(value.total_tokens)
  ) {
    return null;
  }
  if (
    !Array.isArray(value.request_messages) ||
    !value.request_messages.every(isAuditMessagePayload)
  ) {
    return null;
  }
  if (!isRecord(value.request_params)) return null;
  if (value.response_content !== null && typeof value.response_content !== 'string') return null;
  const responseToolCalls = parseNullableMessagePayloads(value.response_tool_calls);
  if (
    value.response_tool_calls !== null &&
    value.response_tool_calls !== undefined &&
    responseToolCalls === null
  ) {
    return null;
  }
  if (value.response_content_hash !== null && typeof value.response_content_hash !== 'string') {
    return null;
  }

  return {
    request_id: value.request_id,
    session_id: value.session_id,
    tenant_id: value.tenant_id,
    api_key_id: value.api_key_id,
    parent_request_id: value.parent_request_id,
    turn_index: value.turn_index,
    match_method: value.match_method,
    change_type: value.change_type,
    model_id: value.model_id,
    provider: value.provider,
    is_stream: value.is_stream,
    status: value.status,
    finish_reason: value.finish_reason,
    truncated: value.truncated,
    created_at: value.created_at,
    prompt_tokens: value.prompt_tokens,
    completion_tokens: value.completion_tokens,
    cached_tokens: value.cached_tokens,
    total_tokens: value.total_tokens,
    request_messages: value.request_messages,
    request_params: value.request_params,
    response_content: value.response_content,
    response_tool_calls: responseToolCalls,
    response_content_hash: value.response_content_hash,
  };
}

function isAdminRole(value: unknown): value is AdminRole {
  return value === 'owner' || value === 'operator' || value === 'auditor';
}

function isAdminActorType(value: unknown): value is AdminActorType {
  return value === 'admin' || value === 'master' || value === 'bootstrap';
}

function isAdminSummary(value: unknown): value is AdminSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.username === 'string' &&
    typeof value.display_name === 'string' &&
    isAdminRole(value.role) &&
    typeof value.active === 'boolean' &&
    typeof value.created_at === 'string' &&
    typeof value.updated_at === 'string' &&
    isNullableString(value.last_login_at)
  );
}

function isAdminSession(value: unknown): value is AdminSession {
  if (!isRecord(value)) return false;
  return (
    isAdminActorType(value.actor_type) &&
    typeof value.name === 'string' &&
    isAdminRole(value.role) &&
    isNullableString(value.admin_id) &&
    isNullableString(value.session_expires_at)
  );
}

function isNullableRecord(value: unknown): value is Record<string, unknown> | null {
  return value === null || value === undefined || isRecord(value);
}

function isAdminAuditEvent(value: unknown): value is AdminAuditEvent {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    isAdminActorType(value.actor_type) &&
    isNullableString(value.actor_id) &&
    typeof value.actor_name === 'string' &&
    typeof value.action === 'string' &&
    typeof value.target_type === 'string' &&
    typeof value.target_id === 'string' &&
    isNullableRecord(value.before) &&
    isNullableRecord(value.after) &&
    isNullableString(value.request_id) &&
    typeof value.created_at === 'string'
  );
}

function parseListPage(
  payload: unknown,
): { items: unknown[]; total: number; limit: number; offset: number } | null {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !isCount(payload.total) ||
    !isCount(payload.limit) ||
    !isCount(payload.offset)
  ) {
    return null;
  }
  return {
    items: payload.items,
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

async function send(
  path: string,
  init: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const callerSignal = init.signal ?? undefined;
  let signal: AbortSignal | undefined;

  try {
    signal = withTimeout(callerSignal, timeoutMs);
    return await fetch(path, { ...init, credentials: 'include', signal });
  } catch (error) {
    if (callerSignal?.aborted) throw error;
    if (signal?.aborted) {
      throw new ApiRequestError({
        status: 0,
        message: `The request timed out after ${Math.round(timeoutMs / 1000)} seconds.`,
      });
    }
    throw new ApiRequestError({
      status: 0,
      message: 'The request did not reach the backend.',
    });
  }
}

async function readJson(response: Response, path: string): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ApiRequestError({
      status: response.status,
      message: `The backend returned an unreadable response for ${path}.`,
      requestId: response.headers.get('x-request-id'),
    });
  }
}

function parseErrorEnvelope(
  value: unknown,
): { message: string; code: string; type: string; requestId: string | null } | null {
  if (!isRecord(value) || !isRecord(value.error)) return null;
  const { message, code, type, request_id } = value.error;
  if (typeof message !== 'string' || typeof code !== 'string' || typeof type !== 'string') {
    return null;
  }
  return {
    message,
    code,
    type,
    requestId: typeof request_id === 'string' ? request_id : null,
  };
}

const ADMIN_HEADERS = { Accept: 'application/json' } as const;

function adminHeaders(method: string, json: boolean): Headers {
  const headers = new Headers(ADMIN_HEADERS);
  if (json) headers.set('Content-Type', 'application/json');
  if (isUnsafeMethod(method)) {
    const csrfToken = readCsrfToken();
    if (csrfToken !== null) headers.set('x-csrf-token', csrfToken);
  }
  return headers;
}

async function adminResponse(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal; timeoutMs?: number },
): Promise<Response> {
  const method = init.method ?? 'GET';
  const response = await send(
    path,
    {
      method,
      signal: init.signal,
      headers: adminHeaders(method, init.body !== undefined),
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    },
    init.timeoutMs,
  );
  if (response.status === 401) reportUnauthorized();
  if (!response.ok) throw await toRequestError(response);
  return response;
}

async function sendAdmin(path: string, signal?: AbortSignal): Promise<Response> {
  return adminResponse(path, { signal });
}

async function sendAdminJson(
  path: string,
  method: 'POST' | 'PATCH' | 'PUT',
  body: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  return adminResponse(path, { method, body, signal });
}

async function sendAdminDelete(path: string, signal?: AbortSignal): Promise<Response> {
  return adminResponse(path, { method: 'DELETE', signal });
}

export async function login(input: LoginInput, signal?: AbortSignal): Promise<LoginResult> {
  const response = await send('/api/v1/auth/login', {
    method: 'POST',
    signal,
    headers: adminHeaders('POST', true),
    body: JSON.stringify(input),
  });
  if (!response.ok) throw await toRequestError(response);

  const payload = await readJson(response, '/api/v1/auth/login');
  if (
    !isRecord(payload) ||
    typeof payload.username !== 'string' ||
    typeof payload.display_name !== 'string' ||
    !isAdminRole(payload.role) ||
    !isAdminActorType(payload.actor_type) ||
    typeof payload.expires_at !== 'string'
  ) {
    throw unexpectedPayload(response, 'login');
  }
  return {
    username: payload.username,
    display_name: payload.display_name,
    role: payload.role,
    actor_type: payload.actor_type,
    expires_at: payload.expires_at,
  };
}

export async function logout(signal?: AbortSignal): Promise<void> {
  const response = await send('/api/v1/auth/logout', {
    method: 'POST',
    signal,
    headers: adminHeaders('POST', false),
  });
  // A missing session still means the browser is signed out.
  if (response.status === 401) return;
  if (!response.ok) throw await toRequestError(response);
}

export async function getCurrentAdmin(signal?: AbortSignal): Promise<AdminSession | null> {
  const response = await send('/api/v1/auth/me', {
    signal,
    headers: adminHeaders('GET', false),
  });
  if (response.status === 401) return null;
  if (!response.ok) throw await toRequestError(response);

  const payload = await readJson(response, '/api/v1/auth/me');
  if (!isAdminSession(payload)) {
    throw unexpectedPayload(response, 'current admin');
  }
  return payload;
}

export async function listAdmins(
  options: { limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<AdminListResponse> {
  const limit = options.limit ?? 50;
  const offset = options.offset ?? 0;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const response = await sendAdmin(`/api/v1/admins?${params.toString()}`, signal);
  const payload = await readJson(response, '/api/v1/admins');
  const page = parseListPage(payload);
  if (page === null || !page.items.every(isAdminSummary)) {
    throw unexpectedPayload(response, 'admin list');
  }
  return {
    items: page.items,
    total: page.total,
    limit: page.limit,
    offset: page.offset,
  };
}

export async function createAdmin(
  input: CreateAdminInput,
  signal?: AbortSignal,
): Promise<AdminSummary> {
  const response = await sendAdminJson('/api/v1/admins', 'POST', input, signal);
  const payload = await readJson(response, '/api/v1/admins');
  if (!isAdminSummary(payload)) {
    throw unexpectedPayload(response, 'admin');
  }
  return payload;
}

export async function updateAdmin(
  adminId: string,
  patch: UpdateAdminInput,
  signal?: AbortSignal,
): Promise<AdminSummary> {
  const path = `/api/v1/admins/${encodeURIComponent(adminId)}`;
  const response = await sendAdminJson(path, 'PATCH', patch, signal);
  const payload = await readJson(response, path);
  if (!isAdminSummary(payload)) {
    throw unexpectedPayload(response, 'admin');
  }
  return payload;
}

function adminAuditQueryParams(query: AdminAuditQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.actorId !== null && query.actorId !== '') params.set('actor_id', query.actorId);
  if (query.action !== null && query.action !== '') params.set('action', query.action);
  if (query.targetType !== null && query.targetType !== '') {
    params.set('target_type', query.targetType);
  }
  if (query.targetId !== null && query.targetId !== '') params.set('target_id', query.targetId);
  if (query.since !== null && query.since !== '') params.set('since', query.since);
  if (query.until !== null && query.until !== '') params.set('until', query.until);
  params.set('limit', String(query.limit));
  params.set('offset', String(query.offset));
  return params;
}

export async function listAdminAudit(
  query: AdminAuditQuery,
  signal?: AbortSignal,
): Promise<AdminAuditListResponse> {
  const path = `/api/v1/admin-audit?${adminAuditQueryParams(query).toString()}`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, '/api/v1/admin-audit');
  const page = parseListPage(payload);
  if (page === null || !page.items.every(isAdminAuditEvent)) {
    throw unexpectedPayload(response, 'admin audit list');
  }
  return {
    items: page.items,
    total: page.total,
    limit: page.limit,
    offset: page.offset,
  };
}

function unexpectedPayload(response: Response, label: string): ApiRequestError {
  return new ApiRequestError({
    status: response.status,
    message: `The backend returned an unexpected ${label} payload.`,
    requestId: response.headers.get('x-request-id'),
  });
}

async function readTenant(response: Response, path: string): Promise<TenantSummary> {
  const payload = await readJson(response, path);
  if (!isTenantSummary(payload)) {
    throw unexpectedPayload(response, 'tenant');
  }
  return payload;
}

function usageWindowQuery(window: UsageWindow): URLSearchParams {
  const params = new URLSearchParams();
  if (window.tenantId !== null && window.tenantId !== '') {
    params.set('tenant_id', window.tenantId);
  }
  params.set('since', window.since);
  if (window.until !== undefined && window.until !== '') {
    params.set('until', window.until);
  }
  return params;
}

async function toRequestError(response: Response): Promise<ApiRequestError> {
  const headerRequestId = response.headers.get('x-request-id');
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const envelope = parseErrorEnvelope(payload);
  return new ApiRequestError({
    status: response.status,
    message: envelope?.message ?? `The request failed with HTTP ${response.status}.`,
    code: envelope?.code,
    requestId: envelope?.requestId ?? headerRequestId,
    errorType: envelope?.type,
  });
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await send('/healthz', {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw await toRequestError(response);

  const payload = await readJson(response, '/healthz');
  if (!isRecord(payload) || payload.status !== 'ok' || typeof payload.version !== 'string') {
    throw new ApiRequestError({
      status: response.status,
      message: 'The backend returned an unexpected health payload.',
    });
  }
  return { status: 'ok', version: payload.version };
}

export async function getReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  const response = await send('/readyz', {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok && response.status !== 503) throw await toRequestError(response);

  const payload = await readJson(response, '/readyz');
  const validStatus =
    isRecord(payload) && (payload.status === 'ok' || payload.status === 'unavailable');
  if (!validStatus || !isStringRecord(payload.checks)) {
    throw new ApiRequestError({
      status: response.status,
      message: 'The backend returned an unexpected readiness payload.',
    });
  }
  return { status: payload.status as ReadinessResponse['status'], checks: payload.checks };
}

export async function listModels(signal?: AbortSignal): Promise<ModelListResponse> {
  const response = await sendAdmin('/api/v1/models?limit=100&offset=0', signal);
  const payload = await readJson(response, '/api/v1/models');
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isModelSummary) ||
    !isCount(payload.total) ||
    !isCount(payload.limit) ||
    !isCount(payload.offset)
  ) {
    throw unexpectedPayload(response, 'model list');
  }

  return {
    items: payload.items,
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

export async function listTenants(
  signal?: AbortSignal,
  options: TenantPageOptions = {},
): Promise<TenantListResponse> {
  const limit = options.limit ?? 100;
  const offset = options.offset ?? 0;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const response = await sendAdmin(`/api/v1/tenants?${params.toString()}`, signal);
  const payload = await readJson(response, '/api/v1/tenants');
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isTenantSummary) ||
    !isCount(payload.total) ||
    !isCount(payload.limit) ||
    !isCount(payload.offset)
  ) {
    throw unexpectedPayload(response, 'tenant list');
  }

  return {
    items: payload.items,
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

export async function createModel(
  input: CreateModelInput,
  signal?: AbortSignal,
): Promise<ModelSummary> {
  const response = await sendAdminJson('/api/v1/models', 'POST', input, signal);
  const payload = await readJson(response, '/api/v1/models');
  if (!isModelSummary(payload)) {
    throw unexpectedPayload(response, 'model');
  }
  return payload;
}

export async function updateModel(
  modelId: string,
  patch: UpdateModelInput,
  signal?: AbortSignal,
): Promise<ModelSummary> {
  const path = `/api/v1/models/${encodeURIComponent(modelId)}`;
  const response = await sendAdminJson(path, 'PATCH', patch, signal);
  const payload = await readJson(response, path);
  if (!isModelSummary(payload)) {
    throw unexpectedPayload(response, 'model');
  }
  return payload;
}

export async function deleteModel(modelId: string, signal?: AbortSignal): Promise<void> {
  await sendAdminDelete(`/api/v1/models/${encodeURIComponent(modelId)}`, signal);
}

export async function listDeployments(
  modelId: string,
  signal?: AbortSignal,
): Promise<DeploymentListResponse> {
  const path = `/api/v1/models/${encodeURIComponent(modelId)}/deployments`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, path);
  if (
    !isRecord(payload) ||
    typeof payload.model_id !== 'string' ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isDeployment)
  ) {
    throw unexpectedPayload(response, 'deployment list');
  }
  return { model_id: payload.model_id, items: payload.items };
}

export async function createDeployment(
  modelId: string,
  input: CreateDeploymentInput,
  signal?: AbortSignal,
): Promise<ModelDeployment> {
  const path = `/api/v1/models/${encodeURIComponent(modelId)}/deployments`;
  const response = await sendAdminJson(path, 'POST', input, signal);
  const payload = await readJson(response, path);
  if (!isDeployment(payload)) {
    throw unexpectedPayload(response, 'deployment');
  }
  return payload;
}

export async function updateDeployment(
  deploymentId: string,
  input: UpdateDeploymentInput,
  signal?: AbortSignal,
): Promise<ModelDeployment> {
  const path = `/api/v1/deployments/${encodeURIComponent(deploymentId)}`;
  const response = await sendAdminJson(path, 'PATCH', input, signal);
  const payload = await readJson(response, path);
  if (!isDeployment(payload)) {
    throw unexpectedPayload(response, 'deployment');
  }
  return payload;
}

export async function deleteDeployment(deploymentId: string, signal?: AbortSignal): Promise<void> {
  await sendAdminDelete(`/api/v1/deployments/${encodeURIComponent(deploymentId)}`, signal);
}

export async function getTenantModelAccess(
  tenantId: string,
  signal?: AbortSignal,
): Promise<TenantModelAccess> {
  const path = `/api/v1/tenants/${encodeURIComponent(tenantId)}/model-access`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, path);
  if (!isTenantModelAccess(payload)) {
    throw unexpectedPayload(response, 'tenant model access');
  }
  return payload;
}

export async function replaceTenantModelAccess(
  tenantId: string,
  input: TenantModelAccessInput,
  signal?: AbortSignal,
): Promise<TenantModelAccess> {
  const path = `/api/v1/tenants/${encodeURIComponent(tenantId)}/model-access`;
  const response = await sendAdminJson(path, 'PUT', input, signal);
  const payload = await readJson(response, path);
  if (!isTenantModelAccess(payload)) {
    throw unexpectedPayload(response, 'tenant model access');
  }
  return payload;
}

export async function createTenant(
  input: CreateTenantInput,
  signal?: AbortSignal,
): Promise<TenantSummary> {
  const response = await sendAdminJson('/api/v1/tenants', 'POST', input, signal);
  return readTenant(response, '/api/v1/tenants');
}

export async function updateTenantLimits(
  tenantId: string,
  patch: TenantLimitsPatch,
  signal?: AbortSignal,
): Promise<TenantSummary> {
  const path = `/api/v1/tenants/${encodeURIComponent(tenantId)}`;
  const response = await sendAdminJson(path, 'PATCH', patch, signal);
  return readTenant(response, path);
}

export async function getTenantBilling(
  tenantId: string,
  signal?: AbortSignal,
): Promise<TenantBillingSummary> {
  const path = `/api/v1/tenants/${encodeURIComponent(tenantId)}/billing`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, path);
  if (!isTenantBillingSummary(payload)) {
    throw unexpectedPayload(response, 'tenant billing summary');
  }
  return payload;
}

export async function listModelPrices(
  modelId: string,
  signal?: AbortSignal,
): Promise<ModelPriceListResponse> {
  const path = `/api/v1/models/${encodeURIComponent(modelId)}/prices?limit=50&offset=0`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, path);
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isModelPrice) ||
    !isCount(payload.total) ||
    !isCount(payload.limit) ||
    !isCount(payload.offset)
  ) {
    throw unexpectedPayload(response, 'model price list');
  }

  return {
    items: payload.items,
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

export async function createModelPrice(
  modelId: string,
  input: CreateModelPriceInput,
  signal?: AbortSignal,
): Promise<ModelPrice> {
  const path = `/api/v1/models/${encodeURIComponent(modelId)}/prices`;
  const response = await sendAdminJson(path, 'POST', input, signal);
  const payload = await readJson(response, path);
  if (!isModelPrice(payload)) {
    throw unexpectedPayload(response, 'model price');
  }
  return payload;
}

export async function listKeys(
  signal?: AbortSignal,
  options: ApiKeyPageOptions = {},
): Promise<ApiKeyListResponse> {
  const limit = options.limit ?? 20;
  const offset = options.offset ?? 0;
  const params = new URLSearchParams();
  if (options.tenantId !== undefined && options.tenantId !== null && options.tenantId !== '') {
    params.set('tenant_id', options.tenantId);
  }
  params.set('limit', String(limit));
  params.set('offset', String(offset));

  const response = await sendAdmin(`/api/v1/keys?${params.toString()}`, signal);
  const payload = await readJson(response, '/api/v1/keys');
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isApiKeySummary) ||
    !isCount(payload.total) ||
    !isCount(payload.limit) ||
    !isCount(payload.offset) ||
    !isNullableString(payload.tenant_id)
  ) {
    throw unexpectedPayload(response, 'API key list');
  }

  return {
    items: payload.items,
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
    tenant_id: payload.tenant_id,
  };
}

export async function createKey(
  input: CreateApiKeyInput,
  signal?: AbortSignal,
): Promise<CreatedApiKey> {
  const response = await sendAdminJson('/api/v1/keys', 'POST', input, signal);
  const payload = await readJson(response, '/api/v1/keys');
  if (!isCreatedApiKey(payload)) {
    throw unexpectedPayload(response, 'created API key');
  }
  return payload;
}

export async function revokeKey(keyId: string, signal?: AbortSignal): Promise<void> {
  const path = `/api/v1/keys/${encodeURIComponent(keyId)}`;
  await sendAdminDelete(path, signal);
}

export async function updateApiKeyLimits(
  keyId: string,
  patch: ApiKeyLimitsPatch,
  signal?: AbortSignal,
): Promise<ApiKeySummary> {
  const path = `/api/v1/keys/${encodeURIComponent(keyId)}`;
  const response = await sendAdminJson(path, 'PATCH', patch, signal);
  const payload = await readJson(response, path);
  if (!isApiKeySummary(payload)) {
    throw unexpectedPayload(response, 'API key');
  }
  return payload;
}

export async function getUsageSummary(
  window: UsageWindow,
  signal?: AbortSignal,
): Promise<UsageSummaryResponse> {
  const path = `/api/v1/usage/summary?${usageWindowQuery(window).toString()}`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, '/api/v1/usage/summary');
  if (
    !isRecord(payload) ||
    !isUsageCounts(payload) ||
    !Array.isArray(payload.by_model) ||
    !payload.by_model.every(isUsageModelSummary)
  ) {
    throw unexpectedPayload(response, 'usage summary');
  }

  return {
    prompt_tokens: payload.prompt_tokens,
    completion_tokens: payload.completion_tokens,
    cached_tokens: payload.cached_tokens,
    total_tokens: payload.total_tokens,
    requests: payload.requests,
    covered_tokens: payload.covered_tokens,
    billable_tokens: payload.billable_tokens,
    list_cost: payload.list_cost,
    billed_cost: payload.billed_cost,
    by_model: payload.by_model,
  };
}

export async function getUsageSeries(
  window: UsageWindow,
  signal?: AbortSignal,
): Promise<UsageSeriesResponse> {
  const params = usageWindowQuery(window);
  params.set('bucket', 'day');
  const path = `/api/v1/usage/series?${params.toString()}`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, '/api/v1/usage/series');
  if (
    !isRecord(payload) ||
    !isUsageBucket(payload.bucket) ||
    !Array.isArray(payload.points) ||
    !payload.points.every(isUsagePoint)
  ) {
    throw unexpectedPayload(response, 'usage series');
  }

  return { bucket: payload.bucket, points: payload.points };
}

export async function getUsageByKey(
  window: UsageWindow,
  signal?: AbortSignal,
  limit = 100,
): Promise<UsageByKeyResponse> {
  const params = usageWindowQuery(window);
  params.set('limit', String(limit));
  const path = `/api/v1/usage/by-key?${params.toString()}`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, '/api/v1/usage/by-key');
  if (
    !isRecord(payload) ||
    !isCount(payload.limit) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isKeyUsageSummary)
  ) {
    throw unexpectedPayload(response, 'usage by key');
  }

  return { limit: payload.limit, items: payload.items };
}

function auditSessionQueryParams(query: AuditSessionQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.tenantId !== null && query.tenantId !== '') params.set('tenant_id', query.tenantId);
  if (query.apiKeyId !== null && query.apiKeyId !== '') params.set('api_key_id', query.apiKeyId);
  if (query.modelId !== null && query.modelId !== '') params.set('model_id', query.modelId);
  if (query.q !== null && query.q !== '') params.set('q', query.q);
  params.set('since', query.since);
  if (query.until !== undefined && query.until !== null && query.until !== '') {
    params.set('until', query.until);
  }
  params.set('limit', String(query.limit));
  params.set('offset', String(query.offset));
  return params;
}

export async function getAuditSessions(
  query: AuditSessionQuery,
  signal?: AbortSignal,
): Promise<AuditSessionPage> {
  const path = `/api/v1/audit/sessions?${auditSessionQueryParams(query).toString()}`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, '/api/v1/audit/sessions');
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isAuditSessionSummary) ||
    !isCount(payload.total) ||
    !isCount(payload.limit) ||
    !isCount(payload.offset)
  ) {
    throw unexpectedPayload(response, 'audit session list');
  }

  return {
    items: payload.items,
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

export async function getAuditSession(
  sessionId: string,
  includeContent: boolean,
  signal?: AbortSignal,
): Promise<AuditSessionDetailResponse> {
  const params = new URLSearchParams();
  if (includeContent) params.set('include_content', 'true');
  const query = params.size > 0 ? `?${params.toString()}` : '';
  const path = `/api/v1/audit/sessions/${encodeURIComponent(sessionId)}${query}`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, path);
  if (
    !isRecord(payload) ||
    !isAuditSessionSummary(payload.session) ||
    !Array.isArray(payload.turns)
  ) {
    throw unexpectedPayload(response, 'audit session');
  }

  const turns: AuditTurn[] = [];
  for (const rawTurn of payload.turns) {
    const turn = parseAuditTurn(rawTurn);
    if (turn === null) throw unexpectedPayload(response, 'audit session');
    turns.push(turn);
  }

  return { session: payload.session, turns };
}

export async function getAuditRequest(
  requestId: string,
  signal?: AbortSignal,
): Promise<AuditRequestDetailResponse> {
  const path = `/api/v1/audit/requests/${encodeURIComponent(requestId)}`;
  const response = await sendAdmin(path, signal);
  const payload = await readJson(response, path);
  if (!isRecord(payload) || typeof payload.truncated !== 'boolean') {
    throw unexpectedPayload(response, 'audit request');
  }

  const request = parseAuditRequestDetail(payload.request);
  if (request === null) throw unexpectedPayload(response, 'audit request');

  const diff = payload.diff === null ? null : parseAuditDiff(payload.diff);
  if (payload.diff !== null && diff === null) throw unexpectedPayload(response, 'audit request');

  return { request, diff, truncated: payload.truncated };
}

const AUDIT_EXPORT_TIMEOUT_MS = 120_000;

function exportFilename(response: Response, format: AuditExportFormat): string {
  const disposition = response.headers.get('Content-Disposition');
  const match = disposition?.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1]?.trim();
  return filename !== undefined && filename.length > 0 ? filename : `audit-export.${format}`;
}

export async function exportAuditRequests(
  query: AuditExportQuery,
  signal?: AbortSignal,
): Promise<AuditExportFile> {
  if (query.tenantId === '') {
    throw new ApiRequestError({ status: 0, message: 'Select a tenant before exporting.' });
  }
  const params = new URLSearchParams({
    tenant_id: query.tenantId,
    since: query.since,
    until: query.until,
    format: query.format,
  });
  const path = `/api/v1/audit/export?${params.toString()}`;
  const response = await adminResponse(path, { signal, timeoutMs: AUDIT_EXPORT_TIMEOUT_MS });

  let blob: Blob;
  try {
    blob = await response.blob();
  } catch {
    throw new ApiRequestError({
      status: response.status,
      message: 'The backend returned an unreadable audit export.',
      requestId: response.headers.get('x-request-id'),
    });
  }
  return { blob, filename: exportFilename(response, query.format) };
}

export async function deleteAuditRequests(
  query: AuditDeleteQuery,
  signal?: AbortSignal,
): Promise<AuditDeleteResult> {
  if (query.tenantId === '') {
    throw new ApiRequestError({ status: 0, message: 'Select a tenant before deleting.' });
  }
  const params = new URLSearchParams({
    tenant_id: query.tenantId,
    before: query.before,
    dry_run: String(query.dryRun ?? false),
  });
  if (query.batchSize !== undefined) params.set('batch_size', String(query.batchSize));
  if (query.maxBatches !== undefined) params.set('max_batches', String(query.maxBatches));

  const path = `/api/v1/audit?${params.toString()}`;
  const response = await sendAdminDelete(path, signal);
  const payload = await readJson(response, path);
  if (!isAuditDeleteResult(payload)) {
    throw unexpectedPayload(response, 'audit delete result');
  }
  return payload;
}
