import { useId, useState, type ReactNode, type RefObject } from 'react';

import type { ModelDeployment, ModelSummary } from '../api/client';
import {
  useCreateDeployment,
  useDeleteDeployment,
  useDeployments,
  useUpdateDeployment,
} from '../hooks/useDeployments';
import { formatCreatedAt } from '../lib/format';
import { Button } from './Button';
import { AlertTriangleIcon, CloseIcon, PlusIcon } from './Icons';
import { DeploymentForm } from './DeploymentForm';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface DeploymentDialogProps {
  model: ModelSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}

type View =
  | { kind: 'list' }
  | { kind: 'create' }
  | { kind: 'edit'; deployment: ModelDeployment }
  | { kind: 'delete'; deployment: ModelDeployment };

export function DeploymentDialog({ model, returnFocusRef, onClose }: DeploymentDialogProps) {
  const [view, setView] = useState<View>({ kind: 'list' });
  const [notice, setNotice] = useState<string | null>(null);
  const titleId = useId();
  const deploymentsQuery = useDeployments(model.id);
  const createMutation = useCreateDeployment(model.id);
  const updateMutation = useUpdateDeployment(model.id);
  const deleteMutation = useDeleteDeployment(model.id);

  const pending = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending;

  const backToList = (message: string | null) => {
    setView({ kind: 'list' });
    setNotice(message);
  };

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={pending}
      returnFocusRef={returnFocusRef}
      panelClassName="max-w-2xl"
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div className="min-w-0">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Registry
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Deployments
          </h3>
          <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">{model.id}</p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close deployments dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <div className="px-5 py-4">
        <p className="rounded border border-line bg-surface-sunken/40 px-2.5 py-1.5 text-[11.5px] leading-5 text-ink-muted">
          请求按权重随机分流，失败会切换到其他部署，连续失败的部署进入冷却。
        </p>
        <p className="mt-2 text-[11.5px] leading-5 text-ink-muted">
          <span className="font-mono text-ink">credential_env</span> names an environment variable
          on the gateway. It is never a secret and never returned by the API; the key itself stays
          on the server.
        </p>

        {notice !== null && (
          <p
            role="status"
            className="mt-3 rounded border border-ok/25 bg-ok-soft px-2.5 py-1.5 text-[11.5px] text-ok"
          >
            {notice}
          </p>
        )}

        {view.kind === 'create' ? (
          <div className="mt-4">
            <DeploymentForm
              mode="create"
              initial={null}
              pending={createMutation.isPending}
              error={createMutation.error}
              onSubmitCreate={(input) =>
                createMutation.mutate(input, {
                  onSuccess: (created) => backToList(`Deployment '${created.name}' added.`),
                })
              }
              onSubmitUpdate={() => undefined}
              onCancel={() => {
                createMutation.reset();
                backToList(null);
              }}
              onDirty={() => {
                if (createMutation.isError) createMutation.reset();
              }}
            />
          </div>
        ) : view.kind === 'edit' ? (
          <div className="mt-4">
            <DeploymentForm
              mode="edit"
              initial={view.deployment}
              pending={updateMutation.isPending}
              error={updateMutation.error}
              onSubmitCreate={() => undefined}
              onSubmitUpdate={(input) =>
                updateMutation.mutate(
                  { deploymentId: view.deployment.id, input },
                  {
                    onSuccess: (updated) => backToList(`Deployment '${updated.name}' updated.`),
                  },
                )
              }
              onCancel={() => {
                updateMutation.reset();
                backToList(null);
              }}
              onDirty={() => {
                if (updateMutation.isError) updateMutation.reset();
              }}
            />
          </div>
        ) : view.kind === 'delete' ? (
          <DeleteConfirmation
            deployment={view.deployment}
            pending={deleteMutation.isPending}
            error={deleteMutation.error}
            onCancel={() => {
              deleteMutation.reset();
              backToList(null);
            }}
            onConfirm={() =>
              deleteMutation.mutate(view.deployment.id, {
                onSuccess: () => backToList(`Deployment '${view.deployment.name}' deleted.`),
              })
            }
          />
        ) : (
          <DeploymentList
            query={deploymentsQuery}
            onCreate={() => {
              setNotice(null);
              createMutation.reset();
              setView({ kind: 'create' });
            }}
            onEdit={(deployment) => {
              setNotice(null);
              updateMutation.reset();
              setView({ kind: 'edit', deployment });
            }}
            onDelete={(deployment) => {
              setNotice(null);
              deleteMutation.reset();
              setView({ kind: 'delete', deployment });
            }}
          />
        )}
      </div>
    </Modal>
  );
}

function DeploymentList({
  query,
  onCreate,
  onEdit,
  onDelete,
}: {
  query: ReturnType<typeof useDeployments>;
  onCreate: () => void;
  onEdit: (deployment: ModelDeployment) => void;
  onDelete: (deployment: ModelDeployment) => void;
}) {
  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          Deployment targets
        </h4>
        {query.status === 'success' && (
          <span className="font-mono text-[10px] tabular-nums text-ink-muted">
            {query.data.items.length === 1
              ? '1 deployment'
              : `${query.data.items.length} deployments`}
          </span>
        )}
      </div>

      <div className="mt-1.5">
        {query.isPending ? (
          <DeploymentSkeleton />
        ) : query.isError ? (
          <RequestErrorPanel
            error={query.error}
            title="Could not load deployments"
            retryLabel="Retry loading deployments"
            onRetry={() => void query.refetch()}
          />
        ) : query.data.items.length === 0 ? (
          <p className="rounded-md border border-dashed border-line-strong px-3 py-4 text-[12px] leading-5 text-ink-muted">
            No explicit deployments. Requests use the model&apos;s provider and upstream model as a
            single default deployment.
          </p>
        ) : (
          <ul
            aria-label="Deployment targets"
            className="divide-y divide-line overflow-hidden rounded-md border border-line"
          >
            {query.data.items.map((deployment) => (
              <li key={deployment.id} className="px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="break-words font-mono text-[12.5px] font-medium text-ink">
                      {deployment.name}
                    </p>
                    <p className="mt-0.5 break-words text-[11px] text-ink-muted">
                      {deployment.provider} ·{' '}
                      <span className="font-mono">{deployment.upstream_model}</span>
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-0.5">
                    <Button
                      variant="ghost"
                      onClick={() => onEdit(deployment)}
                      aria-label={`Edit deployment ${deployment.name}`}
                      title="Edit deployment"
                      className="px-2 py-1 text-[12px]"
                    >
                      Edit
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => onDelete(deployment)}
                      aria-label={`Delete deployment ${deployment.name}`}
                      title="Delete deployment"
                      className="px-2 py-1 text-[12px] text-danger hover:bg-danger-soft hover:text-danger"
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] sm:grid-cols-4">
                  <DeploymentFact label="weight">
                    <span className="tabular-nums">{deployment.weight}</span>
                  </DeploymentFact>
                  <DeploymentFact label="enabled">
                    <span
                      className={
                        deployment.enabled
                          ? 'rounded border border-ok/25 bg-ok-soft px-1 py-0.5 text-[10px] text-ok'
                          : 'rounded border border-line-strong bg-surface-sunken px-1 py-0.5 text-[10px] text-ink-muted'
                      }
                    >
                      {deployment.enabled ? 'On' : 'Off'}
                    </span>
                  </DeploymentFact>
                  <DeploymentFact label="credential_env">
                    {deployment.credential_env === null ? (
                      <span className="text-ink-muted">Provider default</span>
                    ) : (
                      <span className="break-all font-mono">{deployment.credential_env}</span>
                    )}
                  </DeploymentFact>
                  <DeploymentFact label="base_url">
                    {deployment.base_url === null ? (
                      <span className="text-ink-muted">Provider default</span>
                    ) : (
                      <span className="break-all font-mono">{deployment.base_url}</span>
                    )}
                  </DeploymentFact>
                  <DeploymentFact label="created">
                    <time dateTime={deployment.created_at} className="tabular-nums">
                      {formatCreatedAt(deployment.created_at)}
                    </time>
                  </DeploymentFact>
                </dl>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-3 flex justify-end">
        <Button onClick={onCreate}>
          <PlusIcon className="size-3.5" />
          Add deployment
        </Button>
      </div>
    </div>
  );
}

function DeploymentFact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="font-mono text-[9.5px] uppercase tracking-[0.08em] text-ink-muted">{label}</dt>
      <dd className="break-words text-ink">{children}</dd>
    </div>
  );
}

function DeleteConfirmation({
  deployment,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  deployment: ModelDeployment;
  pending: boolean;
  error: Error | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="mt-4">
      <h4 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
        Delete deployment
      </h4>
      <p className="mt-2 flex items-start gap-2 rounded border border-danger/30 bg-danger-soft/60 px-2.5 py-2 text-[12px] text-danger">
        <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
        <span>
          Requests routed only to <span className="font-mono">{deployment.name}</span> may fail
          until another deployment is enabled. This cannot be undone.
        </span>
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[12px]">
        <DeploymentFact label="upstream_model">
          <span className="font-mono">{deployment.upstream_model}</span>
        </DeploymentFact>
        <DeploymentFact label="weight">
          <span className="tabular-nums">{deployment.weight}</span>
        </DeploymentFact>
      </dl>

      {error !== null && (
        <div className="mt-3">
          <RequestErrorPanel error={error} title="Could not delete deployment" />
        </div>
      )}

      <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
        <Button variant="secondary" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button
          onClick={onConfirm}
          disabled={pending}
          className="bg-danger text-white hover:bg-danger/90 disabled:bg-line-strong disabled:text-ink-muted"
        >
          {pending ? 'Deleting…' : 'Delete deployment'}
        </Button>
      </div>
    </div>
  );
}

function DeploymentSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading deployments…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1].map((row) => (
          <div key={row} className="rounded border border-line/70 px-3 py-2.5">
            <span className="block h-2.5 w-1/3 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <div className="mt-2 grid grid-cols-4 gap-2">
              {[0, 1, 2, 3].map((cell) => (
                <span
                  key={cell}
                  className="h-2.5 w-3/4 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
