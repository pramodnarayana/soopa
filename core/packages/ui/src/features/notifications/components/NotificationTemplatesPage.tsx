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

import { ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import DOMPurify from 'dompurify';
import { Bell, Eye, FileText, Mail, MessageSquare, Plus, Save, Trash2 } from 'lucide-react';
import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';

const Editor = lazy(() => import('@monaco-editor/react'));
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

const CHANNEL_ICONS: Record<Channel, React.ElementType> = {
  EMAIL: Mail,
  IN_APP: Bell,
  SLACK: MessageSquare,
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
  const [name, setName] = useState(template?.name ?? '');
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
    if (!name.trim()) return toast.error('Template name is required');
    if (!eventType.trim()) return toast.error('Event type is required');
    upsert.mutate(
      {
        name: name.trim(),
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
    <Dialog open={true} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="6xl" className="p-0 gap-0 overflow-hidden bg-slate-50">
        <div className="flex items-center justify-between px-6 py-4 bg-white border-b border-slate-200">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center border border-indigo-100">
              <FileText className="w-5 h-5 text-indigo-600" />
            </div>
            <div>
              <DialogTitle className="text-xl font-bold text-slate-900">
                {template ? 'Edit Notification Template' : 'New Notification Template'}
              </DialogTitle>
              <DialogDescription className="text-sm mt-0.5">
                Design Jinja2 templates and preview them with mock data.
              </DialogDescription>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button
              onClick={handleSave}
              disabled={upsert.isPending}
              className="gap-2 bg-indigo-600 hover:bg-indigo-700"
            >
              <Save className="w-4 h-4" />
              {upsert.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-6 p-6">
          {/* Top Tabs for Channel Selection - strictly horizontally aligned at the top */}
          <div className="flex justify-center border-b border-slate-200 pb-4">
            <div className="flex gap-2 p-1 bg-slate-100/50 rounded-lg border border-slate-200 shadow-inner w-fit">
              {ALL_CHANNELS.map((ch) => {
                const Icon = CHANNEL_ICONS[ch];
                const isActive = channel === ch;
                return (
                  <button
                    key={ch}
                    type="button"
                    disabled={!!template}
                    onClick={() => setChannel(ch)}
                    className={`flex items-center gap-2 px-6 py-2.5 rounded-md text-sm font-semibold transition-all ${
                      isActive
                        ? 'bg-white text-indigo-700 shadow-sm border border-slate-200/60'
                        : 'text-slate-600 hover:bg-slate-200/50 border border-transparent'
                    } disabled:opacity-50 disabled:cursor-not-allowed`}
                  >
                    <Icon className="w-4 h-4" />
                    {ch.replace('_', ' ')}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Metadata Row */}
          <div className="grid grid-cols-3 gap-6">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Template Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Invoice Payment Failed - Email"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100 shadow-sm"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Event Type
              </label>
              <input
                type="text"
                value={eventType}
                onChange={(e) => setEventType(e.target.value)}
                disabled={!!template}
                placeholder="e.g. invoice.payment_failed"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50 disabled:text-slate-400 shadow-sm"
              />
            </div>
            {channel === 'EMAIL' ? (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Subject Line{' '}
                  <span className="text-slate-400 font-normal normal-case">(Jinja2 supported)</span>
                </label>
                <input
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="e.g. Payment failed for invoice {{ invoice_id }}"
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100 shadow-sm"
                />
              </div>
            ) : (
              <div /> /* Empty div to maintain grid if no subject */
            )}
          </div>

          {/* Editor + Preview split */}
          <div className="grid grid-cols-2 gap-6 min-h-[400px]">
            {/* Monaco Editor */}
            <div className="flex flex-col gap-2 h-full">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Template Body{' '}
                <span className="text-slate-400 font-normal normal-case">(Jinja2)</span>
              </label>
              <div className="flex-1 rounded-xl border border-slate-200 overflow-hidden shadow-sm bg-white">
                <Suspense
                  fallback={
                    <div className="flex items-center justify-center h-full">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
                    </div>
                  }
                >
                  <Editor
                    defaultLanguage="html"
                    value={body}
                    onChange={(v) => setBody(v ?? '')}
                    theme="light"
                    options={{
                      fontSize: 13,
                      lineNumbers: 'on',
                      minimap: { enabled: false },
                      scrollBeyondLastLine: false,
                      wordWrap: 'on',
                      padding: { top: 16, bottom: 16 },
                    }}
                  />
                </Suspense>
              </div>
            </div>

            {/* Live Preview */}
            <div className="flex flex-col gap-2 h-full">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                <Eye className="w-3.5 h-3.5" /> Live Preview
              </label>
              <div className="flex flex-col gap-4 h-full bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
                {/* Mock Payload */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                    Mock Data (JSON)
                  </label>
                  <textarea
                    value={mockPayload}
                    onChange={(e) => setMockPayload(e.target.value)}
                    rows={4}
                    className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-mono text-slate-700 focus:border-indigo-300 focus:outline-none resize-none"
                  />
                </div>

                {/* Rendered output */}
                <div className="flex flex-col gap-1.5 flex-1 min-h-0">
                  <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                    Rendered Output
                  </label>
                  <div className="flex-1 rounded-lg border border-slate-200 bg-slate-50 p-4 overflow-auto">
                    {previewError ? (
                      <div className="text-sm text-red-600 font-mono bg-red-50 border border-red-200 rounded-lg p-3">
                        {previewError}
                      </div>
                    ) : previewResult ? (
                      <div className="flex flex-col gap-4">
                        {previewResult.rendered_subject && (
                          <div className="pb-3 border-b border-slate-200">
                            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
                              Subject
                            </div>
                            <div className="text-sm font-semibold text-slate-900">
                              {previewResult.rendered_subject}
                            </div>
                          </div>
                        )}
                        <div>
                          <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                            Body
                          </div>
                          {channel === 'EMAIL' ? (
                            <div
                              className="text-sm text-slate-700 bg-white p-4 rounded border border-slate-200 shadow-sm prose prose-sm max-w-none"
                              dangerouslySetInnerHTML={{
                                __html: DOMPurify.sanitize(previewResult.rendered_body),
                              }}
                            />
                          ) : (
                            <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans bg-white p-4 rounded border border-slate-200 shadow-sm">
                              {previewResult.rendered_body}
                            </pre>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="text-sm text-slate-400 flex items-center justify-center h-full">
                        Rendering preview…
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
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
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <span className="text-sm font-semibold text-slate-900">{row.original.name}</span>
      ),
    },
    {
      accessorKey: 'event_type',
      header: 'Event Type',
      cell: ({ row }) => (
        <span className="font-mono text-sm font-medium text-slate-600">
          {row.original.event_type}
        </span>
      ),
    },
    {
      accessorKey: 'channel',
      header: 'Channel',
      cell: ({ row }) => {
        const ch = row.original.channel as Channel;
        const Icon = CHANNEL_ICONS[ch];
        return (
          <Badge
            className={`text-xs font-semibold uppercase flex items-center gap-1.5 w-fit ${CHANNEL_STYLES[ch] ?? 'bg-slate-100 text-slate-700'}`}
          >
            {Icon && <Icon className="w-3.5 h-3.5" />}
            {ch.replace('_', ' ')}
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
          <Button
            onClick={() => setEditing('new')}
            className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm"
          >
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
