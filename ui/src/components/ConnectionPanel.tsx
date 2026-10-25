import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

import { Button } from './Button';
import { Panel, PanelHeader } from './Panel';

const MEMORY_NOTE = 'Kept in memory for this browser session; it is not written to storage.';
const REJECTED_NOTE = 'Disconnect, then connect with another master key.';

interface ConnectionPanelProps {
  connected: boolean;
  rejected: boolean;
  onConnect: (masterKey: string) => void;
  onDisconnect: () => void;
}

export function ConnectionPanel({
  connected,
  rejected,
  onConnect,
  onDisconnect,
}: ConnectionPanelProps) {
  const [draft, setDraft] = useState('');
  const inputId = useId();
  const noteId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const statusRef = useRef<HTMLDivElement>(null);
  const wasConnectedRef = useRef(connected);

  useEffect(() => {
    if (connected) {
      statusRef.current?.focus();
    } else if (wasConnectedRef.current) {
      inputRef.current?.focus();
    }
    wasConnectedRef.current = connected;
  }, [connected]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const masterKey = draft.trim();
    if (masterKey.length === 0) return;
    onConnect(masterKey);
    setDraft('');
  };

  return (
    <Panel labelledBy="connection-heading">
      <PanelHeader id="connection-heading" eyebrow="Session" title="Connection" />
      <div className="p-5">
        {connected ? (
          <div>
            <div
              ref={statusRef}
              role="group"
              tabIndex={-1}
              aria-label={rejected ? 'Master key rejected' : 'Master key loaded'}
              className="flex w-fit items-center gap-2 rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <span
                className={`size-2 rounded-full ${rejected ? 'bg-danger' : 'bg-ok'}`}
                aria-hidden="true"
              />
              <p className={`text-[13px] font-medium ${rejected ? 'text-danger' : 'text-ink'}`}>
                {rejected ? 'Master key rejected' : 'Master key loaded'}
              </p>
            </div>
            <p className="mt-2 text-xs leading-5 text-ink-muted">
              {rejected ? REJECTED_NOTE : MEMORY_NOTE}
            </p>
            <Button variant="secondary" className="mt-4 w-full" onClick={onDisconnect}>
              Disconnect
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <label htmlFor={inputId} className="block text-[13px] font-medium text-ink">
              Master key
            </label>
            <input
              ref={inputRef}
              id={inputId}
              type="password"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              required
              aria-describedby={noteId}
              placeholder="Paste master key"
              className="mt-1.5 block w-full min-w-0 rounded-md border border-line-strong bg-white px-3 py-2 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15"
            />
            <p id={noteId} className="mt-2 text-xs leading-5 text-ink-muted">
              {MEMORY_NOTE}
            </p>
            <Button type="submit" className="mt-4 w-full" disabled={draft.trim().length === 0}>
              Connect
            </Button>
          </form>
        )}
      </div>
    </Panel>
  );
}
