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
}

export interface TenantLimitsPatch {
  monthly_token_quota?: number | null;
  requests_per_minute?: number | null;
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
    isNullableCount(value.requests_per_minute)
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
