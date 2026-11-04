import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { Header } from './components/Header';
import { LoginScreen } from './components/LoginScreen';
import { Panel, PanelHeader } from './components/Panel';
import { RequestErrorPanel } from './components/RequestErrorPanel';
import { AdminSessionProvider } from './components/AdminSessionProvider';
import { StatusPanel } from './components/StatusPanel';
import { Workspace } from './components/Workspace';
import { useBackendStatus, type BackendStatus } from './hooks/useBackendStatus';
import { discardAdminData, useCurrentAdmin, useLogin, useLogout } from './hooks/useSession';
import { adminSessionKey } from './lib/queryKeys';
import { subscribeUnauthorized } from './lib/session';

const SESSION_EXPIRED_MESSAGE = 'Your session expired. Sign in again.';
const SIGNED_OUT_MESSAGE = 'You have been signed out.';

export default function App() {
  const queryClient = useQueryClient();
  const status = useBackendStatus();
  const sessionQuery = useCurrentAdmin();
  const loginMutation = useLogin();
  const logoutMutation = useLogout();
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);

  useEffect(() => {
    return subscribeUnauthorized(() => {
      setSessionNotice(SESSION_EXPIRED_MESSAGE);
      discardAdminData(queryClient);
      queryClient.getMutationCache().clear();
    });
  }, [queryClient]);

  if (sessionQuery.isPending) {
    return <SessionSplash />;
  }

  if (sessionQuery.isError) {
    return (
      <SessionFailure
        error={sessionQuery.error}
        status={status}
        onRetry={() => void sessionQuery.refetch()}
      />
    );
  }

  const session = sessionQuery.data ?? null;

  if (session === null) {
    return (
      <LoginScreen
        notice={sessionNotice}
        error={loginMutation.error}
        pending={loginMutation.isPending || sessionQuery.isFetching}
        status={status}
        onSignIn={(input) => {
          loginMutation.mutate(input, {
            onSuccess: () => {
              setSessionNotice(null);
              void queryClient.invalidateQueries({ queryKey: adminSessionKey });
            },
          });
        }}
        onEdit={() => {
          if (loginMutation.isError) loginMutation.reset();
        }}
      />
    );
  }

  const handleSignOut = () => {
    logoutMutation.mutate(undefined, {
      onSettled: () => setSessionNotice(SIGNED_OUT_MESSAGE),
    });
  };

  return (
    <div className="min-h-screen">
      <div className="h-1 bg-accent" aria-hidden="true" />
      <div className="mx-auto w-full max-w-6xl px-4 pb-16 pt-8 sm:px-6 lg:px-8">
        <Header
          status={status}
          session={session}
          signingOut={logoutMutation.isPending}
          onSignOut={handleSignOut}
        />
        <main className="mt-8 min-w-0 animate-rise [animation-delay:120ms]">
          <AdminSessionProvider session={session}>
            <Workspace />
          </AdminSessionProvider>
        </main>
      </div>
    </div>
  );
}

function SessionSplash() {
  return (
    <div className="min-h-screen">
      <div className="h-1 bg-accent" aria-hidden="true" />
      <div className="flex min-h-[calc(100vh-0.25rem)] flex-col items-center justify-center gap-3 px-4">
        <p className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-ink-muted">
          Admin console
        </p>
        <p role="status" className="text-[15px] font-medium text-ink">
          Checking your session…
        </p>
      </div>
    </div>
  );
}

function SessionFailure({
  error,
  status,
  onRetry,
}: {
  error: Error;
  status: BackendStatus;
  onRetry: () => void;
}) {
  return (
    <div className="min-h-screen">
      <div className="h-1 bg-accent" aria-hidden="true" />
      <div className="mx-auto w-full max-w-md px-4 pb-16 pt-12 sm:px-6">
        <p className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-ink-muted">
          Admin console
        </p>
        <h1 className="mt-2 text-[27px] font-semibold leading-none tracking-[-0.025em] text-ink">
          LLM-GateAway
        </h1>
        <div className="mt-6">
          <Panel labelledBy="session-failure-heading">
            <PanelHeader
              id="session-failure-heading"
              eyebrow="Session"
              title="Session check failed"
            />
            <div className="p-5">
              <RequestErrorPanel
                error={error}
                title="Could not check your session"
                retryLabel="Retry session check"
                onRetry={onRetry}
              />
            </div>
          </Panel>
        </div>
        <div className="mt-4">
          <StatusPanel status={status} />
        </div>
      </div>
    </div>
  );
}
