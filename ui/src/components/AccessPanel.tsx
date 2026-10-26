import { TenantsPanel } from './TenantsPanel';

interface AccessPanelProps {
  masterKey: string | null;
}

export function AccessPanel({ masterKey }: AccessPanelProps) {
  return (
    <div className="space-y-5">
      <TenantsPanel masterKey={masterKey} />
    </div>
  );
}
