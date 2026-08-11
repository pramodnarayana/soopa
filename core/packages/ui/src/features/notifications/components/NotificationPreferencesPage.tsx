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
import { Plus, Save, SlidersHorizontal, Trash2 } from 'lucide-react';
import React, { useState } from 'react';
import { toast } from 'sonner';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { DataTable } from '../../../components/ui/data-table';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/dialog';
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
      next.has(ch) ? next.delete(ch) : next.add(ch);
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
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Event Type
            </label>
            <input
              type="text"
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSave()}
              placeholder="e.g. invoice.payment_failed"
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
              autoFocus
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Delivery Channels
            </label>
            <div className="flex gap-2">
              {ALL_CHANNELS.map((ch) => (
                <button
                  key={ch}
                  type="button"
                  onClick={() => toggle(ch)}
                  aria-pressed={selected.has(ch)}
                  className={`px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
                    selected.has(ch)
                      ? `${CHANNEL_STYLES[ch]} border-transparent`
                      : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
                  }`}
                >
                  {ch}
                </button>
              ))}
            </div>
          </div>
        </div>

        <DialogFooter showCloseButton>
          <Button onClick={handleSave} disabled={isSaving} className="gap-1.5">
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
  const { data: preferences = [], isLoading } = usePreferences(props);
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
            <Badge
              key={ch}
              className={`text-xs font-semibold uppercase ${
                CHANNEL_STYLES[ch as Channel] ?? 'bg-slate-100 text-slate-700'
              }`}
            >
              {ch}
            </Badge>
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
            variant="outline"
            size="sm"
            onClick={() => handleDelete(row.original)}
            className="text-red-600 border-red-200 hover:bg-red-50"
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
          <Button onClick={() => setDialogOpen(true)} className="gap-2">
            <Plus className="w-4 h-4" />
            Add Rule
          </Button>
        </div>
      </section>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 overflow-hidden">
        <DataTable
          table={table}
          columnsLength={columns.length}
          dataLength={preferences.length}
          isLoading={isLoading}
          emptyIcon={<SlidersHorizontal className="w-8 h-8 opacity-50" />}
          emptyTitle="No Rules Configured"
          emptyDescription="Add a rule to start routing notifications to your preferred channels."
        />
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
