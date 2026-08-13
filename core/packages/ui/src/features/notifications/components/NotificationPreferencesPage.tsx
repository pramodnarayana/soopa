/**
 * NotificationPreferencesPage
 *
 * Allows tenant admins to configure which channels (EMAIL, SLACK, IN_APP)
 * receive notifications for a given event type.
 *
 * The "Add Rule" form uses the shared Dialog component — not an invalid
 * <tr> injected outside the DataTable's table element.
 */

import { ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { ChevronDown, Plus, Save, SlidersHorizontal, Trash2 } from 'lucide-react';
import React, { useState } from 'react';
import { toast } from 'sonner';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { DataTable } from '../../../components/ui/data-table';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/dialog';
import { Popover, PopoverContent, PopoverTrigger } from '../../../components/ui/popover';
import {
  type NotificationConfigContext,
  type NotificationPreference,
  useDeletePreference,
  usePreferences,
  useUpsertPreference,
} from '../api/useNotificationConfig';

const ALL_CHANNELS = ['EMAIL', 'IN_APP', 'SLACK'] as const;
type Channel = (typeof ALL_CHANNELS)[number];

const CHANNEL_STYLES: Record<Channel, string> = {
  EMAIL: 'bg-violet-100 text-violet-800',
  IN_APP: 'bg-blue-100 text-blue-800',
  SLACK: 'bg-emerald-100 text-emerald-800',
};

// ---------------------------------------------------------------------------
// Add Rule Dialog
// ---------------------------------------------------------------------------

interface AddRuleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (event_type: string, channels: Channel[]) => void;
  isSaving: boolean;
}

function AddRuleDialog({ open, onOpenChange, onSave, isSaving }: AddRuleDialogProps) {
  const [eventType, setEventType] = useState('');
  const [selected, setSelected] = useState<Set<Channel>>(new Set(['IN_APP']));

  const toggle = (ch: Channel) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(ch)) {
        next.delete(ch);
      } else {
        next.add(ch);
      }
      return next;
    });

  const handleSave = () => {
    if (!eventType.trim()) return toast.error('Event type is required');
    if (selected.size === 0) return toast.error('Select at least one channel');
    onSave(eventType.trim(), [...selected]);
  };

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      setEventType('');
      setSelected(new Set(['IN_APP']));
    }
    onOpenChange(isOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Notification Rule</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-5 py-2">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="event-type-input"
              className="text-xs font-semibold text-slate-500 uppercase tracking-wider"
            >
              Event Type
            </label>
            <input
              id="event-type-input"
              type="text"
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSave()}
              placeholder="e.g. invoice.payment_failed"
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
              autoFocus
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
              Delivery Channels
            </label>
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline">
                  {selected.size > 0
                    ? `${selected.size} channel${selected.size > 1 ? 's' : ''} selected`
                    : 'Select channels...'}
                  <ChevronDown className="w-4 h-4 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-[380px] p-2" align="start" portaled={false}>
                <div className="flex flex-col gap-1">
                  {ALL_CHANNELS.map((ch) => (
                    <label
                      key={ch}
                      className="flex items-center gap-3 px-2 py-2 rounded-md cursor-pointer hover:bg-slate-100 transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(ch)}
                        onChange={() => toggle(ch)}
                        className="w-4 h-4 text-indigo-600 rounded border-slate-300 focus:ring-indigo-500 transition-all cursor-pointer"
                      />
                      <span className="flex-1 text-sm font-medium text-slate-700">
                        {ch.replace('_', ' ')}
                      </span>
                    </label>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>

        <DialogFooter>
          <DialogClose render={<Button variant="outline">Close</Button>} />
          <Button onClick={handleSave} disabled={isSaving}>
            <Save className="w-3.5 h-3.5" />
            {isSaving ? 'Saving…' : 'Save Rule'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export const NotificationPreferencesPage: React.FC<NotificationConfigContext> = (props) => {
  const { data: preferences = [], isLoading, isError } = usePreferences(props);
  const upsert = useUpsertPreference(props);
  const remove = useDeletePreference(props);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleSave = (event_type: string, channels: Channel[]) => {
    upsert.mutate(
      { event_type, channels },
      {
        onSuccess: () => {
          toast.success(`Rule for "${event_type}" saved`);
          setDialogOpen(false);
        },
        onError: () => toast.error('Failed to save rule'),
      },
    );
  };

  const handleDelete = (pref: NotificationPreference) => {
    remove.mutate(pref.event_type, {
      onSuccess: () => toast.success(`Rule for "${pref.event_type}" deleted`),
      onError: () => toast.error('Failed to delete rule'),
    });
  };

  const columns: ColumnDef<NotificationPreference>[] = [
    {
      accessorKey: 'event_type',
      header: 'Event Type',
      cell: ({ row }) => (
        <span className="font-mono text-sm font-medium text-slate-800">
          {row.original.event_type}
        </span>
      ),
    },
    {
      accessorKey: 'channels',
      header: 'Delivery Channels',
      cell: ({ row }) => (
        <div className="flex gap-1.5 flex-wrap">
          {row.original.channels.map((ch) => (
            <Badge key={ch}>{ch}</Badge>
          ))}
        </div>
      ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <div className="flex justify-end">
          <Button
            variant="destructive"
            size="sm"
            onClick={() => handleDelete(row.original)}
            aria-label={`Delete rule for ${row.original.event_type}`}
          >
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      ),
    },
  ];

  const table = useReactTable({
    data: preferences,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <SlidersHorizontal className="w-8 h-8 text-indigo-600" />
              Channel Preferences
            </h2>
            <p className="text-slate-500 text-sm mt-1">
              Configure which channels receive alerts for each event type.
            </p>
          </div>
          <Button onClick={() => setDialogOpen(true)}>
            <Plus className="w-4 h-4" />
            Add Rule
          </Button>
        </div>
      </section>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 overflow-hidden">
        {isError ? (
          <div className="flex flex-col items-center justify-center py-12 text-red-600">
            <SlidersHorizontal className="w-12 h-12 mb-3 opacity-20" />
            <p className="text-lg font-semibold">Failed to load preferences</p>
            <p className="text-sm text-red-500 mt-1">
              Please try refreshing the page or contact support if the issue persists.
            </p>
          </div>
        ) : (
          <DataTable
            table={table}
            columnsLength={columns.length}
            dataLength={preferences.length}
            isLoading={isLoading}
            emptyIcon={<SlidersHorizontal className="w-8 h-8 opacity-50" />}
            emptyTitle="No Rules Configured"
            emptyDescription="Add a rule to start routing notifications to your preferred channels."
          />
        )}
      </div>

      <AddRuleDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSave={handleSave}
        isSaving={upsert.isPending}
      />
    </div>
  );
};
