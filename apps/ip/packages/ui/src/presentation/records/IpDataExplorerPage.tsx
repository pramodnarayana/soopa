import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@soopa/ui';
import { Filter, RefreshCw } from 'lucide-react';
import React, { useState } from 'react';
import { useConnectionsQuery } from '../../application/use-connection-queries';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { IpPageHeader } from '../shared/IpPageHeader';
import { DataExplorer } from './DataExplorer';

export function IpDataExplorerPage() {
  const { navigation } = useIpWorkspace();
  const connectionsQuery = useConnectionsQuery();
  const [selectedConnectionId, setSelectedConnectionId] = useState<string>('all');

  const connections = connectionsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <IpPageHeader
        title="Data Explorer"
        actions={
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <Filter className="h-3.5 w-3.5 text-muted-foreground" />
              <Select
                value={selectedConnectionId}
                onValueChange={(val) => setSelectedConnectionId(val)}
              >
                <SelectTrigger className="h-8 w-48 text-xs">
                  <SelectValue placeholder="All Connections" />
                </SelectTrigger>
                <SelectContent className="text-xs">
                  <SelectItem value="all">All Connections</SelectItem>
                  {connections.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name || c.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void connectionsQuery.refetch()}
              className="gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Refresh</span>
            </Button>
          </div>
        }
      />

      <DataExplorer
        connectionId={selectedConnectionId === 'all' ? undefined : selectedConnectionId}
        onOpenTraceDetail={
          navigation.toTraceDetail ? (traceId) => navigation.toTraceDetail(traceId) : undefined
        }
        onOpenTraceStitches={
          navigation.toTraceStitches
            ? (traceId) => navigation.toTraceStitches?.(traceId)
            : undefined
        }
      />
    </div>
  );
}
