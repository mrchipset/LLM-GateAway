import type { ModelProvider } from '../api/client';

export const MODEL_PROVIDERS: readonly ModelProvider[] = [
  'openai',
  'deepseek',
  'azure',
  'anthropic',
  'fake',
];

export const MODEL_PROVIDER_LABELS: Record<ModelProvider, string> = {
  openai: 'OpenAI',
  deepseek: 'DeepSeek',
  azure: 'Azure OpenAI',
  anthropic: 'Anthropic',
  fake: 'Fake (offline testing)',
};

export function modelProviderLabel(provider: string): string {
  return MODEL_PROVIDER_LABELS[provider as ModelProvider] ?? provider;
}

export const MODEL_ID_MAX_LENGTH = 128;
export const MODEL_ID_PATTERN = /^[A-Za-z0-9._:-]+$/;
export const UPSTREAM_MODEL_MAX_LENGTH = 256;

export interface ModelDraft {
  id: string;
  upstreamModel: string;
}

export interface ModelDraftErrors {
  id?: string;
  upstreamModel?: string;
}

export function validateModelDraft(draft: ModelDraft): ModelDraftErrors {
  const errors: ModelDraftErrors = {};

  if (draft.id.length === 0) {
    errors.id = 'Enter a model id.';
  } else if (draft.id.length > MODEL_ID_MAX_LENGTH) {
    errors.id = `Use ${MODEL_ID_MAX_LENGTH} characters or fewer.`;
  } else if (!MODEL_ID_PATTERN.test(draft.id)) {
    errors.id = 'Use only letters, numbers, and . _ : -';
  }

  const upstream = draft.upstreamModel.trim();
  if (upstream.length === 0) {
    errors.upstreamModel = 'Enter the upstream model name.';
  } else if (upstream.length > UPSTREAM_MODEL_MAX_LENGTH) {
    errors.upstreamModel = `Use ${UPSTREAM_MODEL_MAX_LENGTH} characters or fewer.`;
  }

  return errors;
}
