import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@soopa/ui';
import React from 'react';
import type { ConnectionEntityField } from '../../domain/connection-entity';

export interface SubscribedEntitySchemaPanelProps {
  readonly primaryKey: readonly string[];
  readonly fields: readonly ConnectionEntityField[];
}

export function SubscribedEntitySchemaPanel({
  primaryKey,
  fields,
}: SubscribedEntitySchemaPanelProps) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold text-foreground text-xs uppercase tracking-wider">
          Schema Fields
        </span>
        {primaryKey.length > 0 ? (
          <span className="font-mono text-xs text-muted-foreground">
            Primary Key: {primaryKey.join(', ')}
          </span>
        ) : null}
      </div>
      {fields.length === 0 ? (
        <span className="text-muted-foreground text-xs block">
          No schema fields recorded for this entity.
        </span>
      ) : (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <Table className="text-xs">
            <TableHeader className="bg-muted/50 border-b border-border">
              <TableRow className="hover:bg-transparent border-0">
                <TableHead scope="col" className="py-1.5 px-3 font-medium text-foreground text-xs">
                  Field
                </TableHead>
                <TableHead scope="col" className="py-1.5 px-3 font-medium text-foreground text-xs">
                  Type
                </TableHead>
                <TableHead scope="col" className="py-1.5 px-3 font-medium text-foreground text-xs">
                  Nullable
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {fields.map((f) => (
                <TableRow
                  key={f.name}
                  className="border-b border-border/50 last:border-0 hover:bg-transparent"
                >
                  <TableCell className="py-1 px-3 font-mono text-xs">{f.name}</TableCell>
                  <TableCell className="py-1 px-3 font-mono text-muted-foreground text-xs">
                    {f.dataType}
                  </TableCell>
                  <TableCell className="py-1 px-3 text-muted-foreground text-xs">
                    {f.nullable ? 'Yes' : 'No'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
