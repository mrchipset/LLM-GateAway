import { KeysPanel } from './KeysPanel';
import { TenantsPanel } from './TenantsPanel';

export function AccessPanel() {
  return (
    <div className="space-y-5">
      <TenantsPanel />
      <KeysPanel />
    </div>
  );
}
