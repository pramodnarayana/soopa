import { Badge } from '@soopa/ui';
import { Button, buttonVariants } from '@soopa/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@soopa/ui/components/ui/table';
import { Link } from '@tanstack/react-router';
import { ArrowRight, ChevronDown, ChevronRight } from 'lucide-react';
import React, { useState } from 'react';

interface ColumnDef<T> {
  key: string;
  label: string;
  render?: (item: T) => React.ReactNode;
  className?: string;
}

interface ExplorerTableProps<T> {
  columns: ColumnDef<T>[];
  data: T[];
  isLoading: boolean;
  renderExpanded: (item: T) => React.ReactNode;
  headerToolbar?: React.ReactNode;
  onLoadMore?: () => void;
  hasMore?: boolean;
}

export function ExplorerTable<T extends { id: string; trace_id?: string; status?: string }>({
  columns,
  data,
  isLoading,
  renderExpanded,
  headerToolbar,
  onLoadMore,
  hasMore,
}: ExplorerTableProps<T>) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  const getStatusBadge = (status?: string) => {
    if (!status) return null;
    switch (status.toUpperCase()) {
      case 'RECEIVED':
      case 'ACCEPTED':
      case 'PARSED':
      case 'TRANSFORMED':
      case 'DELIVERED':
        return (
          <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100 border-0">
            SUCCESS
          </Badge>
        );
      case 'FAILED':
      case 'ERROR':
        return <Badge className="bg-red-100 text-red-700 hover:bg-red-100 border-0">FAILURE</Badge>;
      case 'PENDING':
      case 'PENDING_DELIVERY':
        return (
          <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100 border-0">PENDING</Badge>
        );
      default:
        return (
          <Badge className="bg-slate-100 text-slate-700 hover:bg-slate-100 border-0">
            {status}
          </Badge>
        );
    }
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
      {headerToolbar && (
        <div className="border-b border-slate-200 bg-slate-50/50 p-4">{headerToolbar}</div>
      )}
      <Table>
        <TableHeader className="bg-slate-50/80">
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-10"></TableHead>
            {columns.map((col) => (
              <TableHead
                key={col.key}
                className={`font-semibold text-slate-600 ${col.className || ''}`}
              >
                {col.label}
              </TableHead>
            ))}
            <TableHead className="w-24 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={columns.length + 2} className="h-32 text-center text-slate-500">
                <div className="flex items-center justify-center gap-3">
                  <div className="w-5 h-5 rounded-full border-2 border-indigo-200 border-t-indigo-600 animate-spin" />
                  Loading data...
                </div>
              </TableCell>
            </TableRow>
          ) : !data || data.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length + 2} className="h-32 text-center text-slate-500">
                No records found matching your filters.
              </TableCell>
            </TableRow>
          ) : (
            data.map((item) => (
              <React.Fragment key={item.id}>
                <TableRow
                  className={`group cursor-pointer hover:bg-slate-50/50 ${expandedId === item.id ? 'bg-slate-50/50' : ''}`}
                  onClick={() => toggleExpand(item.id)}
                >
                  <TableCell className="p-3">
                    <div className="text-slate-400">
                      {expandedId === item.id ? (
                        <ChevronDown className="w-4 h-4" />
                      ) : (
                        <ChevronRight className="w-4 h-4" />
                      )}
                    </div>
                  </TableCell>
                  {columns.map((col) => (
                    <TableCell key={col.key} className={`py-3 ${col.className || ''}`}>
                      {col.render ? (
                        col.render(item)
                      ) : col.key === 'status' ? (
                        getStatusBadge(item.status)
                      ) : (
                        <span className="text-slate-700 font-medium">
                          {((item as Record<string, unknown>)[col.key] as React.ReactNode) || '-'}
                        </span>
                      )}
                    </TableCell>
                  ))}
                  <TableCell className="text-right py-3" onClick={(e) => e.stopPropagation()}>
                    {item.trace_id && (
                      <Link
                        to="/tenant/explorer/$traceId"
                        params={{ traceId: item.trace_id }}
                        className={buttonVariants({ variant: 'secondary', size: 'sm' })}
                        title="View Trace Timeline"
                      >
                        Trace
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Link>
                    )}
                  </TableCell>
                </TableRow>
                {expandedId === item.id && (
                  <TableRow className="bg-slate-50/50 hover:bg-slate-50/50 border-t-0">
                    <TableCell colSpan={columns.length + 2} className="p-0">
                      <div className="p-6 border-t border-slate-100 animate-in slide-in-from-top-2 duration-200">
                        {renderExpanded(item)}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </React.Fragment>
            ))
          )}
          {hasMore && !isLoading && (
            <TableRow>
              <TableCell colSpan={columns.length + 2} className="h-16 text-center">
                <Button variant="outline" size="sm" onClick={onLoadMore} className="w-48">
                  Load More
                </Button>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
