import { flexRender, type Table as ReactTable } from '@tanstack/react-table';
import React, { Fragment } from 'react';
import { Skeleton } from './skeleton';

interface DataTableProps<TData> {
  table: ReactTable<TData>;
  columnsLength: number;
  isLoading?: boolean;
  dataLength: number;
  emptyIcon?: React.ReactNode;
  emptyTitle?: string;
  emptyDescription?: string;
  renderExpandedRow?: (row: import('@tanstack/react-table').Row<TData>) => React.ReactNode;
  onRowClick?: (row: import('@tanstack/react-table').Row<TData>) => void;
  getGroupBoundary?: (
    row: import('@tanstack/react-table').Row<TData>,
    prevRow: import('@tanstack/react-table').Row<TData>,
  ) => boolean;
}

export function DataTable<TData>({
  table,
  columnsLength,
  isLoading,
  dataLength,
  emptyIcon,
  emptyTitle = 'No Data',
  emptyDescription,
  renderExpandedRow,
  onRowClick,
  getGroupBoundary,
}: DataTableProps<TData>) {
  if (isLoading) {
    return (
      <div className="bg-white border border-slate-200/60 rounded-2xl shadow-sm overflow-hidden flex flex-col">
        <div className="p-8 space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full rounded-xl bg-slate-50" />
          ))}
        </div>
      </div>
    );
  }

  if (dataLength === 0) {
    return (
      <div className="bg-white rounded-2xl border border-slate-200/60 shadow-sm p-12 text-center">
        <div className="w-16 h-16 mx-auto bg-slate-50 rounded-2xl border border-slate-100 flex items-center justify-center mb-4 text-slate-400 shadow-sm">
          {emptyIcon}
        </div>
        <h3 className="text-lg font-semibold text-slate-900 mb-1">{emptyTitle}</h3>
        {emptyDescription && <p className="text-sm text-slate-500 mt-1">{emptyDescription}</p>}
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200/60 rounded-2xl shadow-sm overflow-hidden flex flex-col">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-slate-200/60 bg-slate-50/50">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-6 py-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-left align-middle"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-100">
            {table.getRowModel().rows.map((row, index, rows) => {
              const previousRow = index > 0 ? rows[index - 1] : null;
              const isNewGroup =
                getGroupBoundary && previousRow ? getGroupBoundary(row, previousRow) : false;

              return (
                <Fragment key={row.id}>
                  {isNewGroup && (
                    <tr>
                      <td
                        colSpan={columnsLength}
                        className="p-0 border-t-[6px] border-slate-100/50 bg-slate-50/20"
                      ></td>
                    </tr>
                  )}
                  <tr
                    className={`hover:bg-slate-50/50 transition-colors group ${renderExpandedRow || onRowClick ? 'cursor-pointer' : ''} ${row.getIsExpanded() ? 'bg-slate-50/50' : ''}`}
                    onClick={
                      renderExpandedRow
                        ? () => row.toggleExpanded()
                        : onRowClick
                          ? () => onRowClick(row)
                          : undefined
                    }
                    role={renderExpandedRow || onRowClick ? 'button' : undefined}
                    onKeyDown={
                      renderExpandedRow || onRowClick
                        ? (e) => {
                            const target = e.target as HTMLElement;
                            if (
                              target.tagName === 'BUTTON' ||
                              target.tagName === 'A' ||
                              target.tagName === 'INPUT'
                            )
                              return;
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              if (renderExpandedRow) row.toggleExpanded();
                              else if (onRowClick) onRowClick(row);
                            }
                          }
                        : undefined
                    }
                    tabIndex={renderExpandedRow || onRowClick ? 0 : undefined}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-6 py-4 align-middle">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                  {renderExpandedRow && row.getIsExpanded() && (
                    <tr>
                      <td colSpan={columnsLength} className="p-0">
                        {renderExpandedRow(row)}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
