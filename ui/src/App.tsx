import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { ApiRequestError } from './api/client';
import { ConnectionPanel } from './components/ConnectionPanel';
import { Header } from './components/Header';
import { ModelsPanel } from './components/ModelsPanel';
import { useBackendStatus } from './hooks/useBackendStatus';
import { useModels } from './hooks/useModels';

export default function App() {
  const [masterKey, setMasterKey] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const status = useBackendStatus();
  const modelsQuery = useModels(masterKey);

  const keyRejected =
    masterKey !== null &&
    modelsQuery.isError &&
    modelsQuery.error instanceof ApiRequestError &&
    modelsQuery.error.status === 401;

  const handleDisconnect = () => {
    setMasterKey(null);
    void queryClient.cancelQueries({ queryKey: ['admin-models'] });
    queryClient.removeQueries({ queryKey: ['admin-models'] });
  };

  return (
    <div className="min-h-screen">
      <div className="h-1 bg-accent" aria-hidden="true" />
      <div className="mx-auto w-full max-w-6xl px-4 pb-16 pt-8 sm:px-6 lg:px-8">
        <Header status={status} />
        <main className="mt-8 grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
          <div className="animate-rise [animation-delay:80ms] lg:self-stretch">
            <div className="lg:sticky lg:top-6">
              <ConnectionPanel
                connected={masterKey !== null}
                rejected={keyRejected}
                onConnect={setMasterKey}
                onDisconnect={handleDisconnect}
              />
            </div>
          </div>
          <div className="min-w-0 animate-rise [animation-delay:160ms]">
            <ModelsPanel masterKey={masterKey} query={modelsQuery} />
          </div>
        </main>
      </div>
    </div>
  );
}
