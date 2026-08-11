/**
 * NotificationTemplatesPage
 *
 * Two-panel split layout:
 * - Left: Table of existing (event_type, channel) templates.
 * - Right: Monaco Editor + live preview pane.
 *
 * The preview panel calls the backend /templates/preview endpoint with the
 * same SandboxedEnvironment as production — SSTI errors surface here in real-time.
 */

import Editor from '@monaco-editor/react';
import { ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Eye, FileText, Plus, Save, Trash2 } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { DataTable } from '../../../components/ui/data-table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/dialog';
import {
  type NotificationConfigContext,
  type NotificationTemplate,
  useDeleteTemplate,
  usePreviewTemplate,
  useTemplates,
  useUpsertTemplate,
} from '../api/useNotificationConfig';

const ALL_CHANNELS = ['EMAIL', 'IN_APP', 'SLACK'] as const;
type Channel = (typeof ALL_CHANNELS)[number];

const CHANNEL_STYLES: Record<Channel, string> = {
  EMAIL: 'bg-violet-100 text-violet-800',
  IN_APP: 'bg-blue-100 text-blue-800',
  SLACK: 'bg-emerald-100 text-emerald-800',
};

const DEFAULT_TEMPLATE = `Hello {{ user_name }},

{% if event_type == "invoice.payment_failed" %}
Your payment of {{ amount }} has failed. Please update your payment details.
{% else %}
You have a new notification regarding your account.
{% endif %}

Regards,
The Soopa Team`;

// ---------------------------------------------------------------------------
// Editor Panel
// ---------------------------------------------------------------------------

function TemplateEditorPanel({
  template,
  onClose,
  ctx,
}: {
  template: NotificationTemplate | null;
  onClose: () => void;
  ctx: NotificationConfigContext;
}) {
  const [eventType, setEventType] = useState(template?.event_type ?? '');
  const [channel, setChannel] = useState<Channel>((template?.channel as Channel) ?? 'IN_APP');
  const [subject, setSubject] = useState(template?.subject_template ?? '');
  const [body, setBody] = useState(template?.body_template ?? DEFAULT_TEMPLATE);
  const [mockPayload, setMockPayload] = useState(
    '{\n  "user_name": "Alice",\n  "amount": "$500"\n}',
  );
  const [previewResult, setPreviewResult] = useState<{
    rendered_body: string;
    rendered_subject: string | null;
  } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const upsert = useUpsertTemplate(ctx);
  const { mutate: previewMutate } = usePreviewTemplate(ctx);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runPreview = useCallback(
    (currentBody: string, currentSubject: string, currentPayload: string) => {
      let parsedPayload: Record<string, unknown> = {};
      try {
        parsedPayload = JSON.parse(currentPayload);
      } catch {
        setPreviewError('Mock payload must be valid JSON');
        return;
      }
      setPreviewError(null);
      previewMutate(
        {
          body_template: currentBody,
          subject_template: currentSubject || undefined,
          mock_payload: parsedPayload,
        },
        {
          onSuccess: (r) => setPreviewResult(r),
          onError: (e) => setPreviewError(e.message),
        },
      );
    },
    [previewMutate],
  );

  const schedulePreview = useCallback(
    (b: string, s: string, p: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => runPreview(b, s, p), 600);
    },
    [runPreview],
  );

  useEffect(() => {
    schedulePreview(body, subject, mockPayload);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [body, subject, mockPayload, schedulePreview]);

  const handleSave = () => {
    if (!eventType.trim()) return toast.error('Event type is required');
    upsert.mutate(
      {
        event_type: eventType.trim(),
        channel,
        subject_template: subject || null,
        body_template: body,
        is_active: true,
      },
      {
        onSuccess: () => {
          toast.success('Template saved');
          onClose();
        },
        onError: () => toast.error('Failed to save template'),
      },
    );
  };

  return (
    <div className="flex flex-col gap-6 p-6 bg-white rounded-2xl border border-slate-200/60 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
          <FileText className="w-5 h-5 text-indigo-600" />
          {template ? 'Edit Template' : 'New Template'}
        </h3>
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Event Type
          </label>
          <input
            type="text"
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
            disabled={!!template}
            placeholder="e.g. invoice.payment_failed"
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50 disabled:text-slate-400"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Channel
          </label>
          <div className="flex gap-2">
            {ALL_CHANNELS.map((ch) => (
              <button
                key={ch}
                type="button"
                disabled={!!template}
                onClick={() => setChannel(ch)}
                className={`px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
                  channel === ch
                    ? `${CHANNEL_STYLES[ch]} border-transparent`
                    : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
                } disabled:opacity-60 disabled:cursor-not-allowed`}
              >
                {ch}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Subject (EMAIL only) */}
      {channel === 'EMAIL' && (
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Subject Line
          </label>
          <input
            type="text"
            value={subject}
            onChange={(e) => {
              setSubject(e.target.value);
              schedulePreview(body, e.target.value, mockPayload);
            }}
            placeholder="e.g. Payment failed for invoice {{ invoice_id }}"
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
          />
        </div>
      )}

      {/* Editor + Preview split */}
      <div className="grid grid-cols-2 gap-4 min-h-[420px]">
        {/* Monaco Editor */}
        <div className="flex flex-col gap-2">
          <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Template Body <span className="text-slate-400 font-normal normal-case">(Jinja2)</span>
          </label>
          <div className="rounded-xl border border-slate-200 overflow-hidden h-full min-h-[380px]">
            <Editor
              defaultLanguage="html"
              value={body}
              onChange={(v) => {
                const b = v ?? '';
                setBody(b);
                schedulePreview(b, subject, mockPayload);
              }}
              theme="light"
              options={{
                fontSize: 13,
                lineNumbers: 'on',
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                wordWrap: 'on',
                padding: { top: 12, bottom: 12 },
              }}
            />
          </div>
        </div>

        {/* Live Preview */}
        <div className="flex flex-col gap-2">
          <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <Eye className="w-3.5 h-3.5" /> Live Preview
          </label>
          <div className="flex flex-col gap-3 h-full">
            {/* Mock Payload */}
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                Mock Payload (JSON)
              </label>
              <textarea
                value={mockPayload}
                onChange={(e) => {
                  setMockPayload(e.target.value);
                  schedulePreview(body, subject, e.target.value);
                }}
                rows={5}
                className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-mono text-slate-700 focus:border-indigo-300 focus:outline-none resize-none"
              />
            </div>

            {/* Rendered output */}
            <div className="flex-1 rounded-xl border border-slate-200 bg-slate-50/50 p-4 overflow-auto">
              {previewError ? (
                <div className="text-sm text-red-600 font-mono bg-red-50 border border-red-200 rounded-lg p-3">
                  {previewError}
                </div>
              ) : previewResult ? (
                <div className="flex flex-col gap-3">
                  {previewResult.rendered_subject && (
                    <div>
                      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                        Subject
                      </div>
                      <div className="text-sm font-semibold text-slate-800">
                        {previewResult.rendered_subject}
                      </div>
                    </div>
                  )}
                  <div>
                    <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                      Body
                    </div>
                    <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans">
                      {previewResult.rendered_body}
                    </pre>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-slate-400 italic">Preview loading…</div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Save */}
      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={upsert.isPending} className="gap-2">
          <Save className="w-4 h-4" />
          {upsert.isPending ? 'Saving…' : 'Save Template'}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export const NotificationTemplatesPage: React.FC<NotificationConfigContext> = (props) => {
  const { data: templates = [], isLoading } = useTemplates(props);
  const remove = useDeleteTemplate(props);
  const [editing, setEditing] = useState<NotificationTemplate | 'new' | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [templateToDelete, setTemplateToDelete] = useState<NotificationTemplate | null>(null);

  const handleDeleteClick = (tmpl: NotificationTemplate) => {
    setTemplateToDelete(tmpl);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = () => {
    if (!templateToDelete) return;
    remove.mutate(templateToDelete.id, {
      onSuccess: () => {
        toast.success('Template deleted');
        setDeleteDialogOpen(false);
        setTemplateToDelete(null);
      },
      onError: () => toast.error('Failed to delete template'),
    });
  };

  const columns: ColumnDef<NotificationTemplate>[] = [
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
      accessorKey: 'channel',
      header: 'Channel',
      cell: ({ row }) => {
        const ch = row.original.channel as Channel;
        return (
          <Badge
            className={`text-xs font-semibold uppercase ${CHANNEL_STYLES[ch] ?? 'bg-slate-100 text-slate-700'}`}
          >
            {ch}
          </Badge>
        );
      },
    },
    {
      accessorKey: 'is_active',
      header: 'Status',
      cell: ({ row }) =>
        row.original.is_active ? (
          <Badge className="bg-emerald-100 text-emerald-800 text-xs font-semibold">Active</Badge>
        ) : (
          <Badge className="bg-slate-100 text-slate-500 text-xs font-semibold">Inactive</Badge>
        ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => setEditing(row.original)}>
            Edit
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleDeleteClick(row.original)}
            className="text-red-600 border-red-200 hover:bg-red-50"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      ),
    },
  ];

  const table = useReactTable({
    data: templates,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
              <FileText className="w-8 h-8 text-indigo-600" />
              Notification Templates
            </h2>
            <p className="text-slate-500 text-sm mt-1">
              Design Jinja2 templates for each event type and delivery channel.
            </p>
          </div>
          <Button onClick={() => setEditing('new')} className="gap-2">
            <Plus className="w-4 h-4" />
            New Template
          </Button>
        </div>
      </section>

      {editing && (
        <TemplateEditorPanel
          key={editing === 'new' ? 'new-template' : editing.id}
          template={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          ctx={props}
        />
      )}

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 overflow-hidden">
        <DataTable
          table={table}
          columnsLength={columns.length}
          dataLength={templates.length}
          isLoading={isLoading}
          emptyIcon={<FileText className="w-8 h-8 opacity-50" />}
          emptyTitle="No Templates"
          emptyDescription="Create a template to begin customising your notification messages."
        />
      </div>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Template</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete the template for{' '}
              <strong>{templateToDelete?.event_type}</strong> on{' '}
              <strong>{templateToDelete?.channel}</strong>? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="default"
              onClick={handleDeleteConfirm}
              disabled={remove.isPending}
              className="bg-red-600 hover:bg-red-700"
            >
              {remove.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
