import { useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';

import type { AdminSummary } from '../api/client';
import { ADMIN_PAGE_SIZE, useAdmins } from '../hooks/useAdmins';
import { adminSessionKey } from '../lib/queryKeys';
import { useAdminSession } from '../lib/adminSessionContext';
import { formatCreatedAt, formatExactNumber } from '../lib/format';
import { AdminCreateDialog } from './AdminCreateDialog';
import { AdminEditDialog } from './AdminEditDialog';
import { AdminPasswordDialog } from './AdminPasswordDialog';
import { Button } from './Button';
import { CheckCircleIcon, EditIcon, KeyIcon, PlusIcon, RefreshIcon } from './Icons';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';
import { RoleBadge } from './RoleBadge';

export function AdminsPanel({ active = true }: { active?: boolean }) {
  const { session } = useAdminSession();
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingAdmin, setEditingAdmin] = useState<AdminSummary | null>(null);
  const [passwordAdmin, setPasswordAdmin] = useState<AdminSummary | null>(null);
  const createButtonRef = useRef<HTMLButtonElement>(null);
  const editTriggerRef = useRef<HTMLElement | null>(null);
  const passwordTriggerRef = useRef<HTMLElement | null>(null);

  const query = useAdmins(offset, { enabled: active });

  const count =
    query.status === 'success'
      ? `${formatExactNumber(query.data.total)} ${query.data.total === 1 ? 'admin' : 'admins'}`
      : null;

  const openCreate = () => {
    setNotice(null);
    setCreateOpen(true);
  };

  const openEdit = (admin: AdminSummary, trigger: HTMLButtonElement) => {
    setNotice(null);
    editTriggerRef.current = trigger;
    setEditingAdmin(admin);
  };

  const openPassword = (admin: AdminSummary, trigger: HTMLButtonElement) => {
    setNotice(null);
    passwordTriggerRef.current = trigger;
    setPasswordAdmin(admin);
  };

  const refreshSessionIfSelf = (admin: AdminSummary) => {
    if (admin.username === session.name) {
      void queryClient.invalidateQueries({ queryKey: adminSessionKey });
    }
  };

  return (
    <Panel labelledBy="admins-heading">
      <PanelHeader id="admins-heading" eyebrow="Identity" title="Admins">
        <div className="flex flex-wrap items-center justify-end gap-2">
          {count !== null && (
            <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
              {count}
            </span>
          )}
          <Button
            variant="ghost"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            aria-label="Refresh admins"
          >
            <RefreshIcon
              className={`size-3.5 ${query.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
          <Button ref={createButtonRef} onClick={openCreate}>
            <PlusIcon className="size-3.5" />
            Create admin
          </Button>
        </div>
      </PanelHeader>

      <div className="px-5 py-4" aria-busy={query.isFetching}>
        {notice !== null && (
          <p
            role="status"
            className="mb-3 flex items-center gap-1.5 rounded border border-ok/25 bg-ok-soft px-2.5 py-1.5 text-[12px] text-ok"
          >
            <CheckCircleIcon className="size-3.5" />
            {notice}
          </p>
        )}

        <p className="mb-4 rounded border border-line bg-surface-sunken/40 px-2.5 py-1.5 text-[11.5px] leading-5 text-ink-muted">
          Passwords are write-only. A reset revokes that admin&apos;s sessions immediately, and at
          least one active owner must always remain.
        </p>

        {query.isPending ? (
          <AdminsSkeleton />
        ) : query.isError ? (
          <RequestErrorPanel
            error={query.error}
            title="Could not load admins"
            retryLabel="Retry loading admins"
            onRetry={() => void query.refetch()}
          />
        ) : query.data.items.length === 0 ? (
          <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
            <h3 className="text-sm font-semibold text-ink">No admins yet</h3>
            <p className="mt-1 text-[13px] text-ink-muted">Create the first admin account.</p>
            <Button onClick={openCreate} className="mt-3">
              Create admin
            </Button>
          </div>
        ) : (
          <>
            <AdminsTable
              admins={query.data.items}
              onEdit={openEdit}
              onResetPassword={openPassword}
            />
            <AdminsPagination
              total={query.data.total}
              offset={query.data.offset}
              count={query.data.items.length}
              isFetching={query.isFetching}
              onPrevious={() =>
                setOffset(Math.max(0, (query.data?.offset ?? offset) - ADMIN_PAGE_SIZE))
              }
              onNext={() => setOffset((query.data?.offset ?? offset) + ADMIN_PAGE_SIZE)}
            />
          </>
        )}
      </div>

      {createOpen && (
        <AdminCreateDialog
          returnFocusRef={createButtonRef}
          onClose={() => setCreateOpen(false)}
          onCreated={(admin) => {
            setCreateOpen(false);
            setNotice(`Admin '${admin.username}' created.`);
          }}
        />
      )}

      {editingAdmin !== null && (
        <AdminEditDialog
          admin={editingAdmin}
          returnFocusRef={editTriggerRef}
          onClose={() => setEditingAdmin(null)}
          onSaved={(admin) => {
            setEditingAdmin(null);
            setNotice(`Admin '${admin.username}' updated.`);
            refreshSessionIfSelf(admin);
          }}
        />
      )}

      {passwordAdmin !== null && (
        <AdminPasswordDialog
          admin={passwordAdmin}
          returnFocusRef={passwordTriggerRef}
          onClose={() => setPasswordAdmin(null)}
          onReset={(message) => {
            const admin = passwordAdmin;
            setPasswordAdmin(null);
            setNotice(message);
            if (admin !== null) refreshSessionIfSelf(admin);
          }}
        />
      )}
    </Panel>
  );
}

type AdminAction = (admin: AdminSummary, trigger: HTMLButtonElement) => void;

function ActiveBadge({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[10.5px] font-medium ${
        active ? 'border-ok/25 bg-ok-soft text-ok' : 'border-danger/25 bg-danger-soft text-danger'
      }`}
    >
      <span
        aria-hidden="true"
        className={`size-1.5 rounded-full ${active ? 'bg-ok' : 'bg-danger'}`}
      />
      {active ? 'Active' : 'Inactive'}
    </span>
  );
}

function AdminActions({
  admin,
  onEdit,
  onResetPassword,
  withLabel = false,
}: {
  admin: AdminSummary;
  onEdit: AdminAction;
  onResetPassword: AdminAction;
  withLabel?: boolean;
}) {
  return (
    <div className="flex flex-wrap justify-end gap-0.5">
      <Button
        variant="ghost"
        onClick={(event) => onEdit(admin, event.currentTarget)}
        aria-label={`Edit ${admin.username}`}
        title="Edit admin"
        className="shrink-0 px-2 py-1 text-[12px]"
      >
        <EditIcon className="size-3.5" />
        {withLabel && <span>Edit</span>}
      </Button>
      <Button
        variant="ghost"
        onClick={(event) => onResetPassword(admin, event.currentTarget)}
        aria-label={`Reset password for ${admin.username}`}
        title="Reset password"
        className="shrink-0 px-2 py-1 text-[12px]"
      >
        <KeyIcon className="size-3.5" />
        {withLabel && <span>Reset password</span>}
      </Button>
    </div>
  );
}

function AdminsTable({
  admins,
  onEdit,
  onResetPassword,
}: {
  admins: AdminSummary[];
  onEdit: AdminAction;
  onResetPassword: AdminAction;
}) {
  return (
    <>
      <div className="hidden md:block">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <caption className="sr-only">Admins</caption>
          <colgroup>
            <col className="w-[32%]" />
            <col className="w-[14%]" />
            <col className="w-[14%]" />
            <col className="w-[20%]" />
            <col className="w-[20%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {['Admin', 'Role', 'Status', 'Last sign-in (UTC)', 'Actions'].map((label, index) => (
                <th
                  key={label}
                  scope="col"
                  className={`py-2 pr-3 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted last:pr-0 ${
                    index === 4 ? 'text-right' : 'text-left'
                  }`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {admins.map((admin) => (
              <tr key={admin.id} className="transition-colors hover:bg-surface-sunken/40">
                <th scope="row" className="py-2.5 pr-3 align-top">
                  <span className="block break-words font-medium text-ink">
                    {admin.display_name}
                  </span>
                  <span className="mt-0.5 block break-all font-mono text-[10.5px] text-ink-muted">
                    {admin.username}
                  </span>
                </th>
                <td className="py-2.5 pr-3 align-top">
                  <RoleBadge role={admin.role} />
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <ActiveBadge active={admin.active} />
                </td>
                <td className="py-2.5 pr-3 align-top font-mono text-[11.5px] tabular-nums">
                  {admin.last_login_at === null ? (
                    <span className="text-ink-muted">Never</span>
                  ) : (
                    <time dateTime={admin.last_login_at}>
                      {formatCreatedAt(admin.last_login_at)}
                    </time>
                  )}
                </td>
                <td className="py-2.5 text-right align-top">
                  <AdminActions admin={admin} onEdit={onEdit} onResetPassword={onResetPassword} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul aria-label="Admin cards" className="divide-y divide-line md:hidden">
        {admins.map((admin) => (
          <li key={admin.id} className="py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="break-words font-medium text-ink">{admin.display_name}</p>
                <p className="mt-0.5 break-all font-mono text-[11px] text-ink-muted">
                  {admin.username}
                </p>
              </div>
              <ActiveBadge active={admin.active} />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <RoleBadge role={admin.role} />
              <span className="font-mono text-[10.5px] tabular-nums text-ink-muted">
                Last sign-in:{' '}
                {admin.last_login_at === null ? 'Never' : formatCreatedAt(admin.last_login_at)}
              </span>
            </div>
            <div className="mt-2">
              <AdminActions
                admin={admin}
                onEdit={onEdit}
                onResetPassword={onResetPassword}
                withLabel
              />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

function AdminsPagination({
  total,
  offset,
  count,
  isFetching,
  onPrevious,
  onNext,
}: {
  total: number;
  offset: number;
  count: number;
  isFetching: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (total === 0) return null;

  const from = offset + 1;
  const to = offset + count;
  const hasPrevious = offset > 0;
  const hasNext = offset + count < total;

  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
      <p className="font-mono text-[11px] tabular-nums text-ink-muted">
        Showing {formatExactNumber(from)}–{formatExactNumber(to)} of {formatExactNumber(total)}
      </p>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          onClick={onPrevious}
          disabled={!hasPrevious || isFetching}
          aria-label="Previous admin page"
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          onClick={onNext}
          disabled={!hasNext || isFetching}
          aria-label="Next admin page"
        >
          Next
        </Button>
      </div>
    </div>
  );
}

function AdminsSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading admins…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2].map((row) => (
          <div
            key={row}
            className="grid grid-cols-[1.6fr_0.7fr_0.7fr_1fr_0.9fr] gap-4 rounded border border-line/70 px-3 py-3"
          >
            {[0, 1, 2, 3, 4].map((cell) => (
              <span
                key={cell}
                className="h-3.5 w-4/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
