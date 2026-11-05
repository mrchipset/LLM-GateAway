import { useId, useState, type FormEvent } from 'react';

import type {
  CreateDeploymentInput,
  ModelDeployment,
  ModelProvider,
  UpdateDeploymentInput,
} from '../api/client';
import { MODEL_PROVIDERS, MODEL_PROVIDER_LABELS } from '../lib/models';
import { Button } from './Button';
import { RequestErrorPanel } from './RequestErrorPanel';

interface FieldErrors {
  name?: string;
  upstream?: string;
  weight?: string;
  credentialEnv?: string;
  baseUrl?: string;
}

interface DeploymentFormProps {
  mode: 'create' | 'edit';
  initial: ModelDeployment | null;
  pending: boolean;
  error: Error | null;
  onSubmitCreate: (input: CreateDeploymentInput) => void;
  onSubmitUpdate: (input: UpdateDeploymentInput) => void;
  onCancel: () => void;
  onDirty: () => void;
}

const CREDENTIAL_ENV_PATTERN = /^[A-Z][A-Z0-9_]*$/;
const DEPLOYMENT_NAME_PATTERN = /^[A-Za-z0-9._-]+$/;
const DEPLOYMENT_NAME_MAX_LENGTH = 100;
const UPSTREAM_MODEL_MAX_LENGTH = 256;
const BASE_URL_MAX_LENGTH = 2048;

function initialField(value: string | null): string {
  return value ?? '';
}

function parseWeight(raw: string): number | null {
  const value = raw.trim();
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > 100) return null;
  return parsed;
}

function baseUrlError(raw: string): string | null {
  const value = raw.trim();
  if (value === '') return null;
  if (value.length > BASE_URL_MAX_LENGTH) return `Use ${BASE_URL_MAX_LENGTH} characters or fewer.`;

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return 'Enter a full http:// or https:// URL.';
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return 'Use an http:// or https:// URL.';
  }
  return null;
}

export function DeploymentForm({
  mode,
  initial,
  pending,
  error,
  onSubmitCreate,
  onSubmitUpdate,
  onCancel,
  onDirty,
}: DeploymentFormProps) {
  const [name, setName] = useState(initial?.name ?? '');
  const [provider, setProvider] = useState<ModelProvider>(
    (initial?.provider as ModelProvider | undefined) ?? 'openai',
  );
  const [upstream, setUpstream] = useState(initial?.upstream_model ?? '');
  const [weight, setWeight] = useState(String(initial?.weight ?? 1));
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [credentialEnv, setCredentialEnv] = useState(initialField(initial?.credential_env ?? null));
  const [baseUrl, setBaseUrl] = useState(initialField(initial?.base_url ?? null));
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const titleId = useId();
  const nameId = useId();
  const providerId = useId();
  const upstreamId = useId();
  const weightId = useId();
  const credentialId = useId();
  const baseUrlId = useId();
  const hintId = useId();
  const credentialHintId = useId();
  const nameErrorId = useId();
  const upstreamErrorId = useId();
  const weightErrorId = useId();
  const credentialErrorId = useId();
  const baseUrlErrorId = useId();

  const clearError = (field: keyof FieldErrors) => {
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    onDirty();
  };

  const changed = (): boolean => {
    if (mode === 'create') return true;
    if (initial === null) return false;
    return (
      upstream.trim() !== initial.upstream_model ||
      parseWeight(weight) !== initial.weight ||
      enabled !== initial.enabled ||
      credentialEnv.trim() !== (initial.credential_env ?? '') ||
      baseUrl.trim() !== (initial.base_url ?? '')
    );
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedUpstream = upstream.trim();
    const trimmedCredential = credentialEnv.trim();
    const nextErrors: FieldErrors = {};

    if (mode === 'create') {
      const trimmedName = name.trim();
      if (trimmedName.length === 0) {
        nextErrors.name = 'Enter a deployment name.';
      } else if (trimmedName.length > DEPLOYMENT_NAME_MAX_LENGTH) {
        nextErrors.name = `Use ${DEPLOYMENT_NAME_MAX_LENGTH} characters or fewer.`;
      } else if (!DEPLOYMENT_NAME_PATTERN.test(trimmedName)) {
        nextErrors.name = 'Use only letters, numbers, and . _ -';
      }
    }
    if (trimmedUpstream.length === 0) {
      nextErrors.upstream = 'Enter the upstream model name.';
    } else if (trimmedUpstream.length > UPSTREAM_MODEL_MAX_LENGTH) {
      nextErrors.upstream = `Use ${UPSTREAM_MODEL_MAX_LENGTH} characters or fewer.`;
    }

    const weightValue = parseWeight(weight);
    if (weightValue === null) nextErrors.weight = 'Enter a whole number from 1 to 100.';

    if (trimmedCredential !== '' && !CREDENTIAL_ENV_PATTERN.test(trimmedCredential)) {
      nextErrors.credentialEnv = 'Use capitals, digits, and underscores, starting with a letter.';
    }

    const baseUrlMessage = baseUrlError(baseUrl);
    if (baseUrlMessage !== null) nextErrors.baseUrl = baseUrlMessage;

    setFieldErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;
    if (weightValue === null) return;

    if (mode === 'create') {
      const input: CreateDeploymentInput = {
        name: name.trim(),
        provider,
        upstream_model: trimmedUpstream,
        weight: weightValue,
        enabled,
      };
      if (trimmedCredential !== '') input.credential_env = trimmedCredential;
      if (baseUrl.trim() !== '') input.base_url = baseUrl.trim();
      onSubmitCreate(input);
      return;
    }

    if (initial === null) return;
    const patch: UpdateDeploymentInput = {};
    if (trimmedUpstream !== initial.upstream_model) patch.upstream_model = trimmedUpstream;
    if (weightValue !== initial.weight) patch.weight = weightValue;
    if (enabled !== initial.enabled) patch.enabled = enabled;
    if (trimmedCredential !== (initial.credential_env ?? '')) {
      patch.credential_env = trimmedCredential === '' ? null : trimmedCredential;
    }
    if (baseUrl.trim() !== (initial.base_url ?? '')) {
      patch.base_url = baseUrl.trim() === '' ? null : baseUrl.trim();
    }
    if (Object.keys(patch).length === 0) return;
    onSubmitUpdate(patch);
  };

  const nameDescribedBy = fieldErrors.name === undefined ? hintId : `${hintId} ${nameErrorId}`;
  const upstreamDescribedBy =
    fieldErrors.upstream === undefined ? hintId : `${hintId} ${upstreamErrorId}`;
  const weightDescribedBy =
    fieldErrors.weight === undefined ? hintId : `${hintId} ${weightErrorId}`;
  const credentialDescribedBy =
    fieldErrors.credentialEnv === undefined
      ? credentialHintId
      : `${credentialHintId} ${credentialErrorId}`;
  const baseUrlDescribedBy =
    fieldErrors.baseUrl === undefined ? credentialHintId : `${credentialHintId} ${baseUrlErrorId}`;

  return (
    <form
      noValidate
      onSubmit={handleSubmit}
      aria-busy={pending}
      className="rounded-md border border-line bg-surface-sunken/40 p-3"
      aria-labelledby={titleId}
    >
      <h4
        id={titleId}
        className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted"
      >
        {mode === 'create' ? 'Add deployment' : 'Edit deployment'}
      </h4>
      <p id={hintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
        {mode === 'create'
          ? 'A deployment is one upstream target for this model.'
          : 'Only changed fields are sent.'}
      </p>

      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {mode === 'create' && (
          <div>
            <label htmlFor={nameId} className="block text-[12px] font-medium text-ink">
              Name
            </label>
            <input
              autoFocus
              id={nameId}
              type="text"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                clearError('name');
              }}
              disabled={pending}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={fieldErrors.name !== undefined}
              aria-describedby={nameDescribedBy}
              placeholder="e.g. primary"
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {fieldErrors.name !== undefined && (
              <p id={nameErrorId} role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors.name}
              </p>
            )}
          </div>
        )}

        <div>
          <label htmlFor={providerId} className="block text-[12px] font-medium text-ink">
            Provider
          </label>
          {mode === 'create' ? (
            <select
              id={providerId}
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value as ModelProvider);
                onDirty();
              }}
              disabled={pending}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            >
              {MODEL_PROVIDERS.map((option) => (
                <option key={option} value={option}>
                  {MODEL_PROVIDER_LABELS[option]}
                </option>
              ))}
            </select>
          ) : (
            <p className="mt-1 rounded-md border border-line bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink">
              {initial?.provider ?? '—'}
            </p>
          )}
        </div>

        <div>
          <label htmlFor={upstreamId} className="block text-[12px] font-medium text-ink">
            Upstream model
          </label>
          <input
            id={upstreamId}
            type="text"
            value={upstream}
            onChange={(event) => {
              setUpstream(event.target.value);
              clearError('upstream');
            }}
            disabled={pending}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={fieldErrors.upstream !== undefined}
            aria-describedby={upstreamDescribedBy}
            placeholder="e.g. gpt-4o-mini-2024-07-18"
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
          />
          {fieldErrors.upstream !== undefined && (
            <p id={upstreamErrorId} role="alert" className="mt-1 text-xs text-danger">
              {fieldErrors.upstream}
            </p>
          )}
        </div>

        <div>
          <label htmlFor={weightId} className="block text-[12px] font-medium text-ink">
            Weight (1–100)
          </label>
          <input
            id={weightId}
            type="number"
            min={1}
            max={100}
            step={1}
            inputMode="numeric"
            value={weight}
            onChange={(event) => {
              setWeight(event.target.value);
              clearError('weight');
            }}
            disabled={pending}
            aria-invalid={fieldErrors.weight !== undefined}
            aria-describedby={weightDescribedBy}
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
          />
          {fieldErrors.weight !== undefined && (
            <p id={weightErrorId} role="alert" className="mt-1 text-xs text-danger">
              {fieldErrors.weight}
            </p>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={credentialId} className="block text-[12px] font-medium text-ink">
            Credential env (name only)
          </label>
          <input
            id={credentialId}
            type="text"
            value={credentialEnv}
            onChange={(event) => {
              setCredentialEnv(event.target.value);
              clearError('credentialEnv');
            }}
            disabled={pending}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            aria-invalid={fieldErrors.credentialEnv !== undefined}
            aria-describedby={credentialDescribedBy}
            placeholder="e.g. OPENAI_API_KEY"
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
          />
          {fieldErrors.credentialEnv !== undefined && (
            <p id={credentialErrorId} role="alert" className="mt-1 text-xs text-danger">
              {fieldErrors.credentialEnv}
            </p>
          )}
        </div>

        <div>
          <label htmlFor={baseUrlId} className="block text-[12px] font-medium text-ink">
            Base URL (optional)
          </label>
          <input
            id={baseUrlId}
            type="url"
            value={baseUrl}
            onChange={(event) => {
              setBaseUrl(event.target.value);
              clearError('baseUrl');
            }}
            disabled={pending}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={fieldErrors.baseUrl !== undefined}
            aria-describedby={baseUrlDescribedBy}
            placeholder="https://api.example.com/v1"
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
          />
          {fieldErrors.baseUrl !== undefined && (
            <p id={baseUrlErrorId} role="alert" className="mt-1 text-xs text-danger">
              {fieldErrors.baseUrl}
            </p>
          )}
        </div>
      </div>

      <p id={credentialHintId} className="mt-2 text-[11px] leading-4 text-ink-muted">
        This is the name of a variable on the gateway, never the secret itself. Do not paste a key
        here. Leave it blank to use the provider&apos;s configured key.
      </p>

      <div className="mt-3 flex items-start justify-between gap-3 border-t border-line pt-3">
        <div className="min-w-0">
          <p id={`${titleId}-enabled`} className="text-[12px] font-medium text-ink">
            Enabled
          </p>
          <p className="mt-0.5 text-[11px] leading-4 text-ink-muted">
            Disabled deployments keep their settings but receive no traffic.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-labelledby={`${titleId}-enabled`}
          disabled={pending}
          onClick={() => {
            setEnabled((current) => !current);
            onDirty();
          }}
          className="inline-flex shrink-0 items-center gap-2 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span
            aria-hidden="true"
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              enabled ? 'bg-accent' : 'bg-line-strong'
            }`}
          >
            <span
              className={`absolute top-0.5 size-4 rounded-full bg-white shadow-sm transition-transform ${
                enabled ? 'translate-x-[1.125rem]' : 'translate-x-0.5'
              }`}
            />
          </span>
          <span className="w-6 font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-muted">
            {enabled ? 'On' : 'Off'}
          </span>
        </button>
      </div>

      {error !== null && (
        <div className="mt-3">
          <RequestErrorPanel
            error={error}
            title={mode === 'create' ? 'Could not add deployment' : 'Could not update deployment'}
          />
        </div>
      )}

      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || (mode === 'edit' && !changed())}>
          {pending ? 'Saving…' : mode === 'create' ? 'Add deployment' : 'Save changes'}
        </Button>
      </div>
    </form>
  );
}
