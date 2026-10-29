import {
  type ColumnDef,
  getCoreRowModel,
  getExpandedRowModel,
  type Row,
  useReactTable,
} from '@tanstack/react-table';
import { Bell, Check, Clock } from 'lucide-react';
import React from 'react';
import { toast } from 'sonner';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { DataTable } from '../../../components/ui/data-table';
import { type FieldDef, QueryBuilder, useClientFilter } from '../../../components/ui/query-builder';
import {
  type InAppNotification,
  type NotificationContext,
  NotificationSeverity,
  useMarkNotificationAsRead,
  useNotifications,
} from '../api/useNotifications';

const availableFields: FieldDef[] = [
  { id: 'title', label: 'Title', type: 'text' },
  { id: 'body', label: 'Message', type: 'text' },
  {
    id: 'is_read',
    label: 'Read Status',
    type: 'boolean',
    operators: ['eq'],
  },
  {
    id: 'severity',
    label: 'Severity',
    type: 'enum',
    operators: ['eq', 'neq'],
    options: [
      { label: 'Info', value: NotificationSeverity.INFO },
      { label: 'High', value: NotificationSeverity.HIGH },
      { label: 'Urgent', value: NotificationSeverity.URGENT },
    ],
  },
];

function renderExpandedNotificationRow(row: Row<InAppNotification>): React.ReactNode {
  const notification = row.original;
  const date = new Date(notification.created_at);

  return (
    <div className="flex flex-col gap-6 bg-slate-50/50 p-8" onClick={(e) => e.stopPropagation()}>
      <div className="grid grid-cols-4 gap-4">
        <div className="col-span-1 text-sm font-semibold text-slate-500">ID</div>
        <div className="col-span-3 font-mono text-sm text-slate-700">{notification.id}</div>

        <div className="col-span-1 text-sm font-semibold text-slate-500">Severity</div>
        <div className="col-span-3 text-sm text-slate-700 capitalize">{notification.severity}</div>

        <div className="col-span-1 text-sm font-semibold text-slate-500">Received</div>
        <div className="col-span-3 text-sm text-slate-700">{date.toLocaleString()}</div>

        <div className="col-span-1 text-sm font-semibold text-slate-500">Message</div>
        <div className="col-span-3 text-sm whitespace-pre-wrap text-slate-700">
          {notification.body}
        </div>
      </div>
    </div>
  );
}

export const NotificationsPage: React.FC<NotificationContext> = (props) => {
  const { data: notifications = [], isLoading, isError } = useNotifications(props);
  const markAsRead = useMarkNotificationAsRead(props);

  const handleMarkAsRead = (e: React.MouseEvent, id: string): void => {
    e.stopPropagation();
    markAsRead.mutate(id, {
      onSuccess: (result) => {
        if (!result.ok) {
          toast.error(result.error.message || 'Failed to mark notification as read');
        }
      },
    });
  };

  const { filters, setFilters, filteredData } = useClientFilter(notifications);

  const columns: ColumnDef<InAppNotification>[] = [
    {
      accessorKey: 'severity',
      header: 'Severity',
      cell: ({ row }) => <Badge>{row.original.severity}</Badge>,
    },
    {
      accessorKey: 'title',
      header: 'Message',
      cell: ({ row }) => (
        <div className="flex max-w-xl flex-col gap-1.5">
          <span
            className={`text-base ${!row.original.is_read ? 'font-semibold text-slate-900' : 'font-medium text-slate-700'}`}
          >
            {row.original.title}
          </span>
          <span className="line-clamp-1 text-sm text-slate-500">{row.original.body}</span>
        </div>
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Received',
      cell: ({ row }) => {
        const date = new Date(row.original.created_at);
        return (
          <div className="flex items-center gap-1.5 text-sm font-medium text-slate-600">
            <Clock className="h-4 w-4" />
            {date.toLocaleString()}
          </div>
        );
      },
    },
    {
      id: 'actions',
      header: 'Status',
      cell: ({ row }) =>
        row.original.is_read ? (
          <Badge variant="outline">Read</Badge>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={(e) => handleMarkAsRead(e, row.original.id)}
          >
            <Check className="mr-1.5 h-4 w-4" />
            Mark as Read
          </Button>
        ),
    },
  ];

  const table = useReactTable({
    data: filteredData,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: () => true,
  });

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 flex flex-col gap-10 pb-12 duration-700 ease-out">
      <section className="flex flex-col gap-2 border-b border-slate-200/60 pb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="flex items-center gap-3 text-3xl font-bold tracking-tight text-slate-900">
              <Bell className="h-8 w-8 text-indigo-600" />
              Notifications
            </h2>
          </div>
        </div>
        <p className="mt-1 text-sm text-slate-500">View and manage all system alerts and events.</p>
      </section>

      <div>
        <div className="mb-4 flex justify-end">
          <QueryBuilder fields={availableFields} rules={filters} onChange={setFilters} />
        </div>
        <div className="overflow-hidden rounded-2xl border border-slate-200/60 bg-white shadow-sm">
          {isError ? (
            <div className="flex flex-col items-center justify-center py-12 text-red-600">
              <Bell className="mb-3 h-12 w-12 opacity-20" />
              <p className="text-lg font-semibold">Failed to load notifications</p>
              <p className="mt-1 text-sm text-red-500">
                Please try refreshing the page or contact support if the issue persists.
              </p>
            </div>
          ) : (
            <DataTable
              table={table}
              columnsLength={columns.length}
              dataLength={filteredData.length}
              isLoading={isLoading}
              emptyIcon={<Bell className="h-8 w-8 opacity-50" />}
              emptyTitle="No Notifications"
              emptyDescription="You're all caught up!"
              renderExpandedRow={renderExpandedNotificationRow}
            />
          )}
        </div>
      </div>
    </div>
  );
};
