import { useState } from 'react';

import { KeysPanel } from './KeysPanel';
import { TenantsPanel } from './TenantsPanel';

interface AccessPanelProps {
  onTenantDeleted?: (tenantId: string) => void;
}

export function AccessPanel({ onTenantDeleted }: AccessPanelProps) {
  const [keyTenantFilter, setKeyTenantFilter] = useState('');
  const [keyOffset, setKeyOffset] = useState(0);

  const handleTenantDeleted = (tenantId: string) => {
    if (keyTenantFilter === tenantId) {
      setKeyTenantFilter('');
      setKeyOffset(0);
    }
    onTenantDeleted?.(tenantId);
  };

  const handleKeyTenantFilterChange = (tenantId: string) => {
    setKeyTenantFilter(tenantId);
    setKeyOffset(0);
  };

  return (
    <div className="space-y-5">
      <TenantsPanel onTenantDeleted={handleTenantDeleted} />
      <KeysPanel
        tenantFilter={keyTenantFilter}
        offset={keyOffset}
        onTenantFilterChange={handleKeyTenantFilterChange}
        onOffsetChange={setKeyOffset}
      />
    </div>
  );
}
