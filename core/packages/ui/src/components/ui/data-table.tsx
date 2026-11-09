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
          <td colSpan={columnsLength} className="border-t-2 border-muted bg-muted/20 p-0" />
        </tr>
      ) : null}
      <tr
        className={cn(
          'group border-b transition-colors last:border-b-0 hover:bg-muted/50',
          isInteractive && 'cursor-pointer',
          isSelectedOrExpanded && 'bg-muted',
        )}
        {...getInteractiveRowProps(isInteractive, row, renderExpandedRow, onRowClick)}
      >
        {row.getVisibleCells().map((cell) => (
          <td
            key={cell.id}
            className="whitespace-nowrap px-3 py-2 align-middle text-sm text-foreground"
          >
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
  emptyTitle = 'No results.',
  emptyDescription,
  renderExpandedRow,
  onRowClick,
  getGroupBoundary,
}: DataTableProps<TData>) {
  if (isLoading) {
    return (
      <div className="flex flex-col overflow-hidden rounded-lg border border-border bg-card">
        <div className="space-y-2.5 p-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-9 w-full rounded-md bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  if (dataLength === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center">
        {emptyIcon ? (
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
            {emptyIcon}
          </div>
        ) : null}
        <h3 className="text-sm font-medium text-foreground">{emptyTitle}</h3>
        {emptyDescription ? (
          <p className="mt-1 text-xs text-muted-foreground">{emptyDescription}</p>
        ) : null}
      </div>
    );
  }

  const rows = table.getRowModel().rows;

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-border bg-card">
      <div
        tabIndex={0}
        role="region"
        aria-label={ariaLabel ?? emptyTitle}
        className="scrollbar-thin max-w-full overflow-x-auto focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
      >
        <table className="w-full caption-bottom text-left text-sm">
          <thead className="sticky top-0 z-10 border-b border-border bg-muted/40">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-border">
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
                        'h-9 whitespace-nowrap px-3 text-left align-middle text-xs font-medium text-muted-foreground',
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
