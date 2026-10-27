import { withTimeout } from '../lib/timeout';

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
}

export interface ModelListResponse {
  items: ModelSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface TenantSummary {
  id: string;
  name: string;
  created_at: string;
  monthly_token_quota: number | null;
  requests_per_minute: number | null;
  audit_enabled: boolean;
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
}

export interface CreateApiKeyInput {
  name: string;
  tenant_id: string;
  expires_at?: string;
}

export interface CreateTenantInput {
  name: string;
  audit_enabled?: boolean;
}

export interface TenantLimitsPatch {
  monthly_token_quota?: number | null;
  requests_per_minute?: number | null;
  audit_enabled?: boolean;
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

export interface UsageCounts {
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
    typeof value.created_at === 'string'
  );
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isNullableCount(value: unknown): value is number | null {
  return value === null || isCount(value);
}

function isTenantSummary(value: unknown): value is TenantSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.name === 'string' &&
    typeof value.created_at === 'string' &&
    isNullableCount(value.monthly_token_quota) &&
    isNullableCount(value.requests_per_minute) &&
    typeof value.audit_enabled === 'boolean'
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
    isNullableString(value.last_used_at)
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
    isNullableString(value.expires_at)
  );
}

function isUsageCounts(value: unknown): value is UsageCounts {
  if (!isRecord(value)) return false;
  const { prompt_tokens, completion_tokens, cached_tokens, total_tokens, requests } = value;
  return (
    isCount(prompt_tokens) &&
    isCount(completion_tokens) &&
    isCount(cached_tokens) &&
    isCount(total_tokens) &&
    isCount(requests)
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

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const callerSignal = init.signal ?? undefined;
  let signal: AbortSignal | undefined;

  try {
    signal = withTimeout(callerSignal, REQUEST_TIMEOUT_MS);
    return await fetch(path, { ...init, signal });
  } catch (error) {
    if (callerSignal?.aborted) throw error;
    if (signal?.aborted) {
      throw new ApiRequestError({
        status: 0,
        message: 'The request timed out after 10 seconds.',
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

async function sendAdmin(path: string, masterKey: string, signal?: AbortSignal): Promise<Response> {
  const response = await send(path, {
    signal,
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${masterKey}`,
    },
  });
  if (!response.ok) throw await toRequestError(response);
  return response;
}

async function sendAdminJson(
  path: string,
  masterKey: string,
  method: 'POST' | 'PATCH',
  body: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  const response = await send(path, {
    method,
    signal,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      Authorization: `Bearer ${masterKey}`,
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await toRequestError(response);
  return response;
}

async function sendAdminDelete(
  path: string,
  masterKey: string,
  signal?: AbortSignal,
): Promise<Response> {
  const response = await send(path, {
    method: 'DELETE',
    signal,
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${masterKey}`,
    },
  });
  if (!response.ok) throw await toRequestError(response);
  return response;
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

export async function listModels(
  masterKey: string,
  signal?: AbortSignal,
): Promise<ModelListResponse> {
  const response = await sendAdmin('/api/v1/models?limit=100&offset=0', masterKey, signal);
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
  masterKey: string,
  signal?: AbortSignal,
  options: TenantPageOptions = {},
): Promise<TenantListResponse> {
  const limit = options.limit ?? 100;
  const offset = options.offset ?? 0;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const response = await sendAdmin(`/api/v1/tenants?${params.toString()}`, masterKey, signal);
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

export async function createTenant(
  masterKey: string,
  input: CreateTenantInput,
  signal?: AbortSignal,
): Promise<TenantSummary> {
  const response = await sendAdminJson('/api/v1/tenants', masterKey, 'POST', input, signal);
  return readTenant(response, '/api/v1/tenants');
}

export async function updateTenantLimits(
  masterKey: string,
  tenantId: string,
  patch: TenantLimitsPatch,
  signal?: AbortSignal,
): Promise<TenantSummary> {
  const path = `/api/v1/tenants/${encodeURIComponent(tenantId)}`;
  const response = await sendAdminJson(path, masterKey, 'PATCH', patch, signal);
  return readTenant(response, path);
}

export async function listKeys(
  masterKey: string,
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

  const response = await sendAdmin(`/api/v1/keys?${params.toString()}`, masterKey, signal);
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
  masterKey: string,
  input: CreateApiKeyInput,
  signal?: AbortSignal,
): Promise<CreatedApiKey> {
  const response = await sendAdminJson('/api/v1/keys', masterKey, 'POST', input, signal);
  const payload = await readJson(response, '/api/v1/keys');
  if (!isCreatedApiKey(payload)) {
    throw unexpectedPayload(response, 'created API key');
  }
  return payload;
}

export async function revokeKey(
  masterKey: string,
  keyId: string,
  signal?: AbortSignal,
): Promise<void> {
  const path = `/api/v1/keys/${encodeURIComponent(keyId)}`;
  await sendAdminDelete(path, masterKey, signal);
}

export async function getUsageSummary(
  masterKey: string,
  window: UsageWindow,
  signal?: AbortSignal,
): Promise<UsageSummaryResponse> {
  const path = `/api/v1/usage/summary?${usageWindowQuery(window).toString()}`;
  const response = await sendAdmin(path, masterKey, signal);
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
    by_model: payload.by_model,
  };
}

export async function getUsageSeries(
  masterKey: string,
  window: UsageWindow,
  signal?: AbortSignal,
): Promise<UsageSeriesResponse> {
  const params = usageWindowQuery(window);
  params.set('bucket', 'day');
  const path = `/api/v1/usage/series?${params.toString()}`;
  const response = await sendAdmin(path, masterKey, signal);
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
  masterKey: string,
  window: UsageWindow,
  signal?: AbortSignal,
  limit = 100,
): Promise<UsageByKeyResponse> {
  const params = usageWindowQuery(window);
  params.set('limit', String(limit));
  const path = `/api/v1/usage/by-key?${params.toString()}`;
  const response = await sendAdmin(path, masterKey, signal);
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
  masterKey: string,
  query: AuditSessionQuery,
  signal?: AbortSignal,
): Promise<AuditSessionPage> {
  const path = `/api/v1/audit/sessions?${auditSessionQueryParams(query).toString()}`;
  const response = await sendAdmin(path, masterKey, signal);
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
  masterKey: string,
  sessionId: string,
  includeContent: boolean,
  signal?: AbortSignal,
): Promise<AuditSessionDetailResponse> {
  const params = new URLSearchParams();
  if (includeContent) params.set('include_content', 'true');
  const query = params.size > 0 ? `?${params.toString()}` : '';
  const path = `/api/v1/audit/sessions/${encodeURIComponent(sessionId)}${query}`;
  const response = await sendAdmin(path, masterKey, signal);
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
  masterKey: string,
  requestId: string,
  signal?: AbortSignal,
): Promise<AuditRequestDetailResponse> {
  const path = `/api/v1/audit/requests/${encodeURIComponent(requestId)}`;
  const response = await sendAdmin(path, masterKey, signal);
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
