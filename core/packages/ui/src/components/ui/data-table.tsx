import { flexRender, type Table as ReactTable, type Row } from '@tanstack/react-table';
import React, { Fragment } from 'react';
import { cn } from '../../lib/utils';
import { Skeleton } from './skeleton';

export interface DataTableProps<TData> {
  table: ReactTable<TData>;
  columnsLength: number;
  isLoading?: boolean;
  dataLength: number;
  ariaLabel?: string;
  emptyIcon?: React.ReactNode;
  emptyTitle?: string;
  emptyDescription?: string;
  renderExpandedRow?: (row: Row<TData>) => React.ReactNode;
  onRowClick?: (row: Row<TData>) => void;
  getGroupBoundary?: (row: Row<TData>, prevRow: Row<TData>) => boolean;
}

interface DataTableRowProps<TData> {
  readonly row: Row<TData>;
  readonly columnsLength: number;
  readonly isNewGroup: boolean;
  readonly renderExpandedRow?: (row: Row<TData>) => React.ReactNode;
  readonly onRowClick?: (row: Row<TData>) => void;
}

function activateRow<TData>(
  row: Row<TData>,
  renderExpandedRow?: (row: Row<TData>) => React.ReactNode,
  onRowClick?: (row: Row<TData>) => void,
): void {
  if (renderExpandedRow) {
    row.toggleExpanded();
  } else if (onRowClick) {
    onRowClick(row);
  }
}

function handleInteractiveRowKeyDown<TData>(
  event: React.KeyboardEvent<HTMLTableRowElement>,
  row: Row<TData>,
  renderExpandedRow?: (row: Row<TData>) => React.ReactNode,
  onRowClick?: (row: Row<TData>) => void,
): void {
  const target = event.target as HTMLElement;
  if (target.tagName === 'BUTTON' || target.tagName === 'A' || target.tagName === 'INPUT') {
    return;
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    activateRow(row, renderExpandedRow, onRowClick);
  }
}

function getInteractiveRowProps<TData>(
  isInteractive: boolean,
  row: Row<TData>,
  renderExpandedRow?: (row: Row<TData>) => React.ReactNode,
  onRowClick?: (row: Row<TData>) => void,
): React.HTMLAttributes<HTMLTableRowElement> {
  if (!isInteractive) {
    return {};
  }
  return {
    role: 'button',
    tabIndex: 0,
    onClick: () => activateRow(row, renderExpandedRow, onRowClick),
    onKeyDown: (e) => handleInteractiveRowKeyDown(e, row, renderExpandedRow, onRowClick),
  };
}

function DataTableRow<TData>({
  row,
  columnsLength,
  isNewGroup,
  renderExpandedRow,
  onRowClick,
}: DataTableRowProps<TData>) {
  const isInteractive = Boolean(renderExpandedRow || onRowClick);
  const isSelectedOrExpanded = row.getIsExpanded() || row.getIsSelected();
  const showExpandedContent = Boolean(renderExpandedRow && row.getIsExpanded());

  return (
    <Fragment>
      {isNewGroup ? (
        <tr>
          <td colSpan={columnsLength} className="border-t-4 border-muted bg-muted/20 p-0" />
        </tr>
      ) : null}
      <tr
        className={cn(
          'group transition-colors hover:bg-accent/60',
          isInteractive && 'cursor-pointer',
          isSelectedOrExpanded && 'bg-accent/80',
        )}
        {...getInteractiveRowProps(isInteractive, row, renderExpandedRow, onRowClick)}
      >
        {row.getVisibleCells().map((cell) => (
          <td key={cell.id} className="px-6 py-4 align-middle text-foreground">
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </td>
        ))}
      </tr>
      {showExpandedContent && renderExpandedRow ? (
        <tr>
          <td colSpan={columnsLength} className="p-0">
            {renderExpandedRow(row)}
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}

export function DataTable<TData>({
  table,
  columnsLength,
  isLoading,
  dataLength,
  ariaLabel,
  emptyIcon,
  emptyTitle = 'No Data',
  emptyDescription,
  renderExpandedRow,
  onRowClick,
  getGroupBoundary,
}: DataTableProps<TData>) {
  if (isLoading) {
    return (
      <div className="flex flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-xs">
        <div className="space-y-4 p-8">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full rounded-xl bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  if (dataLength === 0) {
    return (
      <div className="rounded-2xl border border-border bg-card p-12 text-center shadow-xs">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-border bg-muted text-muted-foreground shadow-xs">
          {emptyIcon}
        </div>
        <h3 className="mb-1 text-lg font-semibold text-foreground">{emptyTitle}</h3>
        {emptyDescription ? (
          <p className="mt-1 text-sm text-muted-foreground">{emptyDescription}</p>
        ) : null}
      </div>
    );
  }

  const rows = table.getRowModel().rows;

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-xs">
      <div
        tabIndex={0}
        role="region"
        aria-label={ariaLabel ?? emptyTitle}
        className="max-w-full overflow-x-auto focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <table className="w-full border-separate border-spacing-0 text-left text-sm">
          <thead className="sticky top-0 z-10 bg-muted/90 backdrop-blur-xs">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const rawMeta: unknown = header.column.columnDef.meta;
                  const metaClassName =
                    typeof rawMeta === 'object' &&
                    rawMeta !== null &&
                    'className' in rawMeta &&
                    typeof rawMeta.className === 'string'
                      ? rawMeta.className
                      : undefined;
                  return (
                    <th
                      key={header.id}
                      className={cn(
                        'border-b border-border px-6 py-3.5 text-left align-middle text-xs font-semibold tracking-wider text-muted-foreground uppercase',
                        metaClassName,
                      )}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row, index) => {
              const previousRow = index > 0 ? rows[index - 1] : undefined;
              const isNewGroup = Boolean(
                getGroupBoundary && previousRow && getGroupBoundary(row, previousRow),
              );
              return (
                <DataTableRow
                  key={row.id}
                  row={row}
                  columnsLength={columnsLength}
                  isNewGroup={isNewGroup}
                  renderExpandedRow={renderExpandedRow}
                  onRowClick={onRowClick}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
