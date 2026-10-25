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
  const response = await send('/api/v1/models?limit=100&offset=0', {
    signal,
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${masterKey}`,
    },
  });
  if (!response.ok) throw await toRequestError(response);

  const payload = await readJson(response, '/api/v1/models');
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isModelSummary) ||
    typeof payload.total !== 'number' ||
    typeof payload.limit !== 'number' ||
    typeof payload.offset !== 'number'
  ) {
    throw new ApiRequestError({
      status: response.status,
      message: 'The backend returned an unexpected model list payload.',
    });
  }

  return {
    items: payload.items,
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}
