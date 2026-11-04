import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

import type { LoginInput } from '../api/client';
import type { BackendStatus } from '../hooks/useBackendStatus';
import { ROLE_LABELS, ROLE_SUMMARIES, type AdminRole } from '../lib/session';
import { Button } from './Button';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';
import { StatusPanel } from './StatusPanel';

const ROLES: AdminRole[] = ['owner', 'operator', 'auditor'];

interface LoginScreenProps {
  notice: string | null;
  error: Error | null;
  pending: boolean;
  status: BackendStatus;
  onSignIn: (input: LoginInput) => void;
  onEdit: () => void;
}

export function LoginScreen({
  notice,
  error,
  pending,
  status,
  onSignIn,
  onEdit,
}: LoginScreenProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const usernameId = useId();
  const passwordId = useId();
  const hintId = useId();
  const noticeId = useId();
  const fieldErrorId = useId();
  const usernameRef = useRef<HTMLInputElement>(null);
  const trimmedUsername = username.trim();

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (trimmedUsername === '' || password === '') {
      setFieldError('Enter both a username and a password.');
      return;
    }
    setFieldError(null);
    onSignIn({ username: trimmedUsername, password });
  };

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div className="h-1 bg-accent" aria-hidden="true" />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[26rem] bg-[radial-gradient(60%_100%_at_50%_0%,rgba(31,78,216,0.08),rgba(243,242,238,0))]"
      />
      <div className="relative mx-auto flex min-h-[calc(100vh-0.25rem)] w-full max-w-6xl flex-col px-4 pb-16 pt-8 sm:px-6 lg:px-8">
        <header className="flex animate-rise flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-ink-muted">
              Admin console
            </p>
            <h1 className="mt-2 text-[27px] font-semibold leading-none tracking-[-0.025em] text-ink">
              LLM-GateAway
            </h1>
          </div>
          <p className="font-mono text-xs text-ink-muted">
            Backend version{' '}
            <span className="text-ink">{status.version ? `v${status.version}` : '—'}</span>
          </p>
        </header>

        <main className="mt-10 grid flex-1 items-center gap-10 lg:mt-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,25rem)] lg:gap-16">
          <div className="order-2 animate-rise lg:order-1 [animation-delay:80ms]">
            <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-accent">
              Management plane
            </p>
            <h2 className="mt-3 max-w-xl text-balance text-[32px] font-semibold leading-[1.08] tracking-[-0.03em] text-ink sm:text-[38px]">
              Sign in to run the gateway.
            </h2>
            <p className="mt-4 max-w-lg text-[13.5px] leading-6 text-ink-muted">
              Tenants, API keys, models, and usage all live here. Your role decides what you can
              change; the audit trail keeps the record.
            </p>

            <dl className="mt-8 grid max-w-xl gap-3">
              {ROLES.map((role) => (
                <div key={role} className="flex gap-3 border-l-2 border-line pl-3">
                  <dt className="w-20 shrink-0 pt-0.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.1em] text-ink">
                    {ROLE_LABELS[role]}
                  </dt>
                  <dd className="text-[12px] leading-5 text-ink-muted">{ROLE_SUMMARIES[role]}</dd>
                </div>
              ))}
            </dl>

            <div className="mt-8 max-w-sm">
              <StatusPanel status={status} />
            </div>
          </div>

          <div className="order-1 animate-rise lg:order-2 [animation-delay:160ms]">
            <Panel labelledBy="login-heading">
              <PanelHeader id="login-heading" eyebrow="Session" title="Sign in" />
              <div className="p-5">
                {notice !== null && (
                  <p
                    id={noticeId}
                    role="status"
                    className="mb-4 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[12px] leading-5 text-warn"
                  >
                    {notice}
                  </p>
                )}

                <form onSubmit={handleSubmit} noValidate>
                  <div>
                    <label htmlFor={usernameId} className="block text-[13px] font-medium text-ink">
                      Username
                    </label>
                    <input
                      ref={usernameRef}
                      id={usernameId}
                      type="text"
                      value={username}
                      onChange={(event) => {
                        setUsername(event.target.value);
                        setFieldError(null);
                        onEdit();
                      }}
                      autoComplete="username"
                      autoCapitalize="none"
                      autoCorrect="off"
                      spellCheck={false}
                      aria-describedby={hintId}
                      placeholder="admin"
                      className="mt-1.5 block w-full min-w-0 rounded-md border border-line-strong bg-white px-3 py-2 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15"
                    />
                  </div>

                  <div className="mt-4">
                    <label htmlFor={passwordId} className="block text-[13px] font-medium text-ink">
                      Password
                    </label>
                    <input
                      id={passwordId}
                      type="password"
                      value={password}
                      onChange={(event) => {
                        setPassword(event.target.value);
                        setFieldError(null);
                        onEdit();
                      }}
                      autoComplete="current-password"
                      aria-describedby={fieldError === null ? hintId : `${hintId} ${fieldErrorId}`}
                      className="mt-1.5 block w-full min-w-0 rounded-md border border-line-strong bg-white px-3 py-2 font-mono text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15"
                    />
                  </div>

                  <p id={hintId} className="mt-2 text-xs leading-5 text-ink-muted">
                    The session is held in an HttpOnly cookie. Nothing is stored in this browser.
                  </p>

                  {fieldError !== null && (
                    <p id={fieldErrorId} role="alert" className="mt-2 text-[12px] text-danger">
                      {fieldError}
                    </p>
                  )}

                  <Button
                    type="submit"
                    className="mt-4 w-full"
                    disabled={pending || trimmedUsername === '' || password === ''}
                  >
                    {pending ? 'Signing in…' : 'Sign in'}
                  </Button>
                </form>

                {error !== null && (
                  <div className="mt-4">
                    <RequestErrorPanel error={error} title="Could not sign in" />
                  </div>
                )}
              </div>
            </Panel>
            <p className="mt-3 text-center font-mono text-[10.5px] text-ink-muted">
              Locked out? Ask an owner to reset your password.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
