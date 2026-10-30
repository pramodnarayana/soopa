/**
 * NotificationPreferencesPage
 *
 * Allows tenant admins to configure which channels (EMAIL, SLACK, IN_APP)
 * receive notifications for a given event type.
 */

import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
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

interface AddRuleDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onSave: (event_type: string, channels: Channel[]) => void;
  readonly isSaving: boolean;
}

function AddRuleDialog({ open, onOpenChange, onSave, isSaving }: AddRuleDialogProps) {
  const [eventType, setEventType] = useState('');
  const [selected, setSelected] = useState<Set<Channel>>(new Set(['IN_APP']));

  const toggle = (ch: Channel): void => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(ch)) {
        next.delete(ch);
      } else {
        next.add(ch);
      }
      return next;
    });
  };

  const handleSave = (): void => {
    if (!eventType.trim()) {
      toast.error('Event type is required');
      return;
    }
    if (selected.size === 0) {
      toast.error('Select at least one channel');
      return;
    }
    onSave(eventType.trim(), [...selected]);
  };

  const handleOpenChange = (isOpen: boolean): void => {
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
              className="text-xs font-semibold tracking-wider text-slate-500 uppercase"
            >
              Event Type
            </label>
            <input
              id="event-type-input"
              type="text"
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleSave();
                }
              }}
              placeholder="e.g. invoice.payment_failed"
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none"
              autoFocus
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="mb-1 text-xs font-semibold tracking-wider text-slate-500 uppercase">
              Delivery Channels
            </span>
            <Popover>
              <PopoverTrigger asChild>
                <Button type="button" variant="outline">
                  {selected.size > 0
                    ? `${selected.size} channel${selected.size > 1 ? 's' : ''} selected`
                    : 'Select channels...'}
                  <ChevronDown className="h-4 w-4 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-96 p-2" align="start" portaled={false}>
                <div className="flex flex-col gap-1">
                  {ALL_CHANNELS.map((ch) => (
                    <label
                      key={ch}
                      className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-slate-100"
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(ch)}
                        onChange={() => toggle(ch)}
                        className="h-4 w-4 cursor-pointer rounded border-slate-300 text-indigo-600 transition-all focus:ring-indigo-500"
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
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Close
            </Button>
          </DialogClose>
          <Button type="button" onClick={handleSave} disabled={isSaving}>
            <Save className="h-3.5 w-3.5" />
            {isSaving ? 'Saving…' : 'Save Rule'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export const NotificationPreferencesPage: React.FC<NotificationConfigContext> = (props) => {
  const { data: preferences = [], isLoading, isError } = usePreferences(props);
  const upsert = useUpsertPreference(props);
  const remove = useDeletePreference(props);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleSave = (event_type: string, channels: Channel[]): void => {
    upsert.mutate(
      { event_type, channels },
      {
        onSuccess: (result) => {
          if (!result.ok) {
            toast.error(result.error.message || 'Failed to save rule');
            return;
          }
          toast.success(`Rule for "${event_type}" saved`);
          setDialogOpen(false);
        },
      },
    );
  };

  const handleDelete = (pref: NotificationPreference): void => {
    remove.mutate(pref.event_type, {
      onSuccess: (result) => {
        if (!result.ok) {
          toast.error(result.error.message || 'Failed to delete rule');
          return;
        }
        toast.success(`Rule for "${pref.event_type}" deleted`);
      },
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
        <div className="flex flex-wrap gap-1.5">
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
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => handleDelete(row.original)}
            aria-label={`Delete rule for ${row.original.event_type}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
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
    <div className="animate-in fade-in slide-in-from-bottom-4 flex flex-col gap-10 pb-12 duration-700 ease-out">
      <section className="flex flex-col gap-2 border-b border-slate-200/60 pb-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="flex items-center gap-3 text-3xl font-bold tracking-tight text-slate-900">
              <SlidersHorizontal className="h-8 w-8 text-indigo-600" />
              Channel Preferences
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Configure which channels receive alerts for each event type.
            </p>
          </div>
          <Button type="button" onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4" />
            Add Rule
          </Button>
        </div>
      </section>

      <div className="overflow-hidden rounded-2xl border border-slate-200/60 bg-white shadow-sm">
        {isError ? (
          <div className="flex flex-col items-center justify-center py-12 text-red-600">
            <SlidersHorizontal className="mb-3 h-12 w-12 opacity-20" />
            <p className="text-lg font-semibold">Failed to load preferences</p>
            <p className="mt-1 text-sm text-red-500">
              Please try refreshing the page or contact support if the issue persists.
            </p>
          </div>
        ) : (
          <DataTable
            table={table}
            columnsLength={columns.length}
            dataLength={preferences.length}
            isLoading={isLoading}
            emptyIcon={<SlidersHorizontal className="h-8 w-8 opacity-50" />}
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
