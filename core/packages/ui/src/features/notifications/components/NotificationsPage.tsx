import {
  ColumnDef,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Bell, Check, Clock } from 'lucide-react';
import React from 'react';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { DataTable } from '../../../components/ui/data-table';
import { type FieldDef, QueryBuilder, useClientFilter } from '../../../components/ui/query-builder';
import {
  InAppNotification,
  NotificationContext,
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
      { label: 'Info', value: 'info' },
      { label: 'High', value: 'high' },
      { label: 'Urgent', value: 'urgent' },
    ],
  },
];

export const NotificationsPage: React.FC<NotificationContext> = (props) => {
  const { data: notifications = [], isLoading } = useNotifications(props);
  const markAsRead = useMarkNotificationAsRead(props);

  const handleMarkAsRead = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    markAsRead.mutate(id);
  };

  const enrichedNotifications = React.useMemo(() => {
    return notifications.map((n) => ({
      ...n,
      severity: (n as any).severity || 'info',
    }));
  }, [notifications]);

  const { filters, setFilters, filteredData } = useClientFilter(enrichedNotifications);

  const columns: ColumnDef<InAppNotification>[] = [
    {
      accessorKey: 'severity',
      header: 'Severity',
      cell: ({ row }) => {
        const severity = (row.original as any).severity;
        const colorClass =
          severity === 'urgent'
            ? 'bg-red-100 text-red-800'
            : severity === 'high'
              ? 'bg-orange-100 text-orange-800'
              : 'bg-blue-100 text-blue-800';
        return (
          <Badge className={`uppercase text-xs font-semibold tracking-wider ${colorClass}`}>
            {severity}
          </Badge>
        );
      },
    },
    {
      accessorKey: 'title',
      header: 'Message',
      cell: ({ row }) => (
        <div className="flex flex-col gap-1.5 max-w-xl">
          <span
            className={`text-base ${!row.original.is_read ? 'font-semibold text-slate-900' : 'font-medium text-slate-700'}`}
          >
            {row.original.title}
          </span>
          <span className="text-sm text-slate-500 line-clamp-1">{row.original.body}</span>
        </div>
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Received',
      cell: ({ row }) => {
        const date = new Date(row.original.created_at);
        return (
          <div className="flex items-center gap-1.5 text-sm text-slate-600 font-medium">
            <Clock className="w-4 h-4" />
            {date.toLocaleString()}
          </div>
        );
      },
    },
    {
      id: 'actions',
      header: 'Status',
      cell: ({ row }) => {
        const isRead = row.original.is_read;
        return isRead ? (
          <Badge variant="outline" className="text-slate-500 border-slate-200">
            Read
          </Badge>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={(e) => handleMarkAsRead(e, row.original.id)}
            className="text-indigo-600 border-indigo-200 hover:bg-indigo-50"
          >
            <Check className="w-4 h-4 mr-1.5" />
            Mark as Read
          </Button>
        );
      },
    },
  ];

  const table = useReactTable({
    data: filteredData,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: () => true,
  });

  const renderExpandedRow = (row: import('@tanstack/react-table').Row<InAppNotification>) => {
    const notification = row.original;
    const severity = (notification as any).severity || 'info';
    const date = new Date(notification.created_at);

    return (
      <div className="p-8 bg-slate-50/50 flex flex-col gap-6" onClick={(e) => e.stopPropagation()}>
        <div className="grid grid-cols-[120px_1fr] gap-4">
          <div className="text-sm font-semibold text-slate-500">ID</div>
          <div className="text-sm text-slate-700 font-mono">{notification.id}</div>

          <div className="text-sm font-semibold text-slate-500">Severity</div>
          <div className="text-sm text-slate-700 capitalize">{severity}</div>

          <div className="text-sm font-semibold text-slate-500">Received</div>
          <div className="text-sm text-slate-700">{date.toLocaleString()}</div>

          <div className="text-sm font-semibold text-slate-500">Message</div>
          <div className="text-sm text-slate-700 whitespace-pre-wrap">{notification.body}</div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      {/* Page Header */}
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-3">
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <Bell className="w-8 h-8 text-indigo-600" />
              Notifications
            </h2>
          </div>
        </div>
        <p className="text-slate-500 text-sm mt-1">View and manage all system alerts and events.</p>
      </section>

      <div>
        <div className="mb-4 flex justify-end">
          <QueryBuilder fields={availableFields} rules={filters} onChange={setFilters} />
        </div>
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 overflow-hidden">
          <DataTable
            table={table}
            columnsLength={columns.length}
            dataLength={filteredData.length}
            isLoading={isLoading}
            emptyIcon={<Bell className="w-8 h-8 opacity-50" />}
            emptyTitle="No Notifications"
            emptyDescription="You're all caught up!"
            renderExpandedRow={renderExpandedRow}
          />
        </div>
      </div>
    </div>
  );
};
