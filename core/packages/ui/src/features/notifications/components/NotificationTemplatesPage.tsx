/**
 * NotificationTemplatesPage
 *
 * Two-panel split layout:
 * - Left: Table of existing (event_type, channel) templates.
 * - Right: Monaco Editor + live preview pane.
 */

import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import DOMPurify from 'dompurify';
import { Bell, Eye, FileText, Mail, MessageSquare, Plus, Save, Trash2 } from 'lucide-react';
import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
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
  type PreviewResult,
  useDeleteTemplate,
  usePreviewTemplate,
  useTemplates,
  useUpsertTemplate,
} from '../api/useNotificationConfig';

const Editor = lazy(() => import('@monaco-editor/react'));

const ALL_CHANNELS = ['EMAIL', 'IN_APP', 'SLACK'] as const;
type Channel = (typeof ALL_CHANNELS)[number];

const CHANNEL_SET = new Set<string>(ALL_CHANNELS);

function toChannel(candidate?: string): Channel {
  if (candidate && CHANNEL_SET.has(candidate)) {
    return candidate as Channel;
  }
  return 'IN_APP';
}

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

function parseMockPayloadJson(raw: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return null;
  } catch {
    return null;
  }
}

function TemplatePreviewOutput({
  channel,
  previewError,
  previewResult,
}: {
  readonly channel: Channel;
  readonly previewError: string | null;
  readonly previewResult: PreviewResult | null;
}) {
  if (previewError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 font-mono text-sm text-red-600">
        {previewError}
      </div>
    );
  }
  if (!previewResult) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-400">
        Rendering preview…
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      {previewResult.rendered_subject && (
        <div className="border-b border-slate-200 pb-3">
          <div className="mb-1 text-xs font-semibold tracking-wider text-slate-400 uppercase">
            Subject
          </div>
          <div className="text-sm font-semibold text-slate-900">
            {previewResult.rendered_subject}
          </div>
        </div>
      )}
      <div>
        <div className="mb-2 text-xs font-semibold tracking-wider text-slate-400 uppercase">
          Body
        </div>
        {channel === 'EMAIL' ? (
          <div
            className="max-w-none space-y-2 rounded border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-700 shadow-sm"
            dangerouslySetInnerHTML={{
              __html: DOMPurify.sanitize(previewResult.rendered_body),
            }}
          />
        ) : (
          <pre className="rounded border border-slate-200 bg-white p-4 font-sans text-sm whitespace-pre-wrap text-slate-700 shadow-sm">
            {previewResult.rendered_body}
          </pre>
        )}
      </div>
    </div>
  );
}

function ChannelSelectorTabs({
  channel,
  disabled,
  onSelect,
}: {
  readonly channel: Channel;
  readonly disabled: boolean;
  readonly onSelect: (next: Channel) => void;
}) {
  return (
    <div className="flex justify-center border-b border-slate-200 pb-4">
      <div className="flex w-fit gap-2 rounded-lg border border-slate-200 bg-slate-100/50 p-1 shadow-inner">
        {ALL_CHANNELS.map((ch) => {
          const Icon = CHANNEL_ICONS[ch];
          const isActive = channel === ch;
          return (
            <Button
              key={ch}
              type="button"
              variant={isActive ? 'outline' : 'ghost'}
              disabled={disabled}
              onClick={() => onSelect(ch)}
              className={`gap-2 px-6 py-2.5 text-sm font-semibold ${
                isActive ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600'
              }`}
            >
              <Icon className="h-4 w-4" />
              {ch.replace('_', ' ')}
            </Button>
          );
        })}
      </div>
    </div>
  );
}

interface InitialTemplateForm {
  readonly name: string;
  readonly eventType: string;
  readonly channel: Channel;
  readonly subject: string;
  readonly body: string;
}

function deriveInitialTemplateForm(template: NotificationTemplate | null): InitialTemplateForm {
  if (!template) {
    return {
      name: '',
      eventType: '',
      channel: 'IN_APP',
      subject: '',
      body: DEFAULT_TEMPLATE,
    };
  }
  return {
    name: template.name,
    eventType: template.event_type,
    channel: toChannel(template.channel),
    subject: template.subject_template ?? '',
    body: template.body_template,
  };
}

function TemplateMetadataFields({
  name,
  eventType,
  channel,
  subject,
  isEditingExisting,
  onNameChange,
  onEventTypeChange,
  onSubjectChange,
}: {
  readonly name: string;
  readonly eventType: string;
  readonly channel: Channel;
  readonly subject: string;
  readonly isEditingExisting: boolean;
  readonly onNameChange: (next: string) => void;
  readonly onEventTypeChange: (next: string) => void;
  readonly onSubjectChange: (next: string) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-6">
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
          Template Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="e.g. Invoice Payment Failed - Email"
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
          Event Type
        </label>
        <input
          type="text"
          value={eventType}
          onChange={(e) => onEventTypeChange(e.target.value)}
          disabled={isEditingExisting}
          placeholder="e.g. invoice.payment_failed"
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none disabled:bg-slate-50 disabled:text-slate-400"
        />
      </div>
      {channel === 'EMAIL' ? (
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
            Subject Line{' '}
            <span className="font-normal text-slate-400 normal-case">(Jinja2 supported)</span>
          </label>
          <input
            type="text"
            value={subject}
            onChange={(e) => onSubjectChange(e.target.value)}
            placeholder="e.g. Payment failed for invoice {{ invoice_id }}"
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none"
          />
        </div>
      ) : (
        <div />
      )}
    </div>
  );
}

function TemplateEditorPanel({
  template,
  onClose,
  ctx,
}: {
  readonly template: NotificationTemplate | null;
  readonly onClose: () => void;
  readonly ctx: NotificationConfigContext;
}) {
  const initialForm = deriveInitialTemplateForm(template);
  const [name, setName] = useState(initialForm.name);
  const [eventType, setEventType] = useState(initialForm.eventType);
  const [channel, setChannel] = useState<Channel>(initialForm.channel);
  const [subject, setSubject] = useState(initialForm.subject);
  const [body, setBody] = useState(initialForm.body);
  const [mockPayload, setMockPayload] = useState(
    '{\n  "user_name": "Alice",\n  "amount": "$500"\n}',
  );
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const upsert = useUpsertTemplate(ctx);
  const { mutate: previewMutate } = usePreviewTemplate(ctx);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runPreview = useCallback(
    (currentBody: string, currentSubject: string, currentPayload: string) => {
      const parsedPayload = parseMockPayloadJson(currentPayload);
      if (!parsedPayload) {
        setPreviewError('Mock payload must be valid JSON object');
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
          onSuccess: (result) => {
            if (result.ok) {
              setPreviewResult(result.value);
              setPreviewError(null);
            } else {
              setPreviewError(result.error.message);
            }
          },
        },
      );
    },
    [previewMutate],
  );

  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => runPreview(body, subject, mockPayload), 600);
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [body, subject, mockPayload, runPreview]);

  const handleSave = (): void => {
    if (!name.trim()) {
      toast.error('Template name is required');
      return;
    }
    if (!eventType.trim()) {
      toast.error('Event type is required');
      return;
    }
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
        onSuccess: (result) => {
          if (!result.ok) {
            toast.error(result.error.message || 'Failed to save template');
            return;
          }
          toast.success('Template saved');
          onClose();
        },
      },
    );
  };

  const isEditingExisting = Boolean(template);
  const dialogHeading = isEditingExisting
    ? 'Edit Notification Template'
    : 'New Notification Template';
  const saveButtonLabel = upsert.isPending ? 'Saving…' : 'Save';

  return (
    <Dialog open={true} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-6xl gap-0 overflow-hidden bg-slate-50 p-0">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-indigo-100 bg-indigo-50">
              <FileText className="h-5 w-5 text-indigo-600" />
            </div>
            <div>
              <DialogTitle className="text-xl font-bold text-slate-900">
                {dialogHeading}
              </DialogTitle>
              <DialogDescription className="mt-0.5 text-sm">
                Design Jinja2 templates and preview them with mock data.
              </DialogDescription>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button type="button" onClick={handleSave} disabled={upsert.isPending}>
              <Save className="h-4 w-4" />
              {saveButtonLabel}
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-6 p-6">
          <ChannelSelectorTabs
            channel={channel}
            disabled={isEditingExisting}
            onSelect={setChannel}
          />

          <TemplateMetadataFields
            name={name}
            eventType={eventType}
            channel={channel}
            subject={subject}
            isEditingExisting={isEditingExisting}
            onNameChange={setName}
            onEventTypeChange={setEventType}
            onSubjectChange={setSubject}
          />

          <div className="grid min-h-96 grid-cols-2 gap-6">
            <div className="flex h-full flex-col gap-2">
              <label className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
                Template Body{' '}
                <span className="font-normal text-slate-400 normal-case">(Jinja2)</span>
              </label>
              <div className="flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                <Suspense
                  fallback={
                    <div className="flex h-full items-center justify-center">
                      <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-600" />
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

            <div className="flex h-full flex-col gap-2">
              <label className="flex items-center gap-1.5 text-xs font-semibold tracking-wider text-slate-500 uppercase">
                <Eye className="h-3.5 w-3.5" /> Live Preview
              </label>
              <div className="flex h-full flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs font-semibold tracking-wider text-slate-400 uppercase">
                    Mock Data (JSON)
                  </label>
                  <textarea
                    value={mockPayload}
                    onChange={(e) => setMockPayload(e.target.value)}
                    rows={4}
                    className="resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700 focus:border-indigo-300 focus:outline-none"
                  />
                </div>

                <div className="flex min-h-0 flex-1 flex-col gap-1.5">
                  <label className="text-xs font-semibold tracking-wider text-slate-400 uppercase">
                    Rendered Output
                  </label>
                  <div className="flex-1 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <TemplatePreviewOutput
                      channel={channel}
                      previewError={previewError}
                      previewResult={previewResult}
                    />
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

export const NotificationTemplatesPage: React.FC<NotificationConfigContext> = (props) => {
  const { data: templates = [], isLoading } = useTemplates(props);
  const remove = useDeleteTemplate(props);
  const [editing, setEditing] = useState<NotificationTemplate | 'new' | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [templateToDelete, setTemplateToDelete] = useState<NotificationTemplate | null>(null);

  const handleDeleteClick = (tmpl: NotificationTemplate): void => {
    setTemplateToDelete(tmpl);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = (): void => {
    if (!templateToDelete) {
      return;
    }
    remove.mutate(templateToDelete.id, {
      onSuccess: (result) => {
        if (!result.ok) {
          toast.error(result.error.message || 'Failed to delete template');
          return;
        }
        toast.success('Template deleted');
        setDeleteDialogOpen(false);
        setTemplateToDelete(null);
      },
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
        const ch = toChannel(row.original.channel);
        const Icon = CHANNEL_ICONS[ch];
        return (
          <Badge>
            <Icon className="h-3.5 w-3.5" />
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
          <Badge variant="default">Active</Badge>
        ) : (
          <Badge variant="secondary">Inactive</Badge>
        ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setEditing(row.original)}
          >
            Edit
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => handleDeleteClick(row.original)}
          >
            <Trash2 className="h-3.5 w-3.5" />
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
    <div className="animate-in fade-in slide-in-from-bottom-4 flex flex-col gap-10 pb-12 duration-700 ease-out">
      <section className="flex flex-col gap-2 border-b border-slate-200/60 pb-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="flex items-center gap-3 text-3xl font-bold tracking-tight text-slate-900">
              <FileText className="h-8 w-8 text-indigo-600" />
              Notification Templates
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Design Jinja2 templates for each event type and delivery channel.
            </p>
          </div>
          <Button type="button" onClick={() => setEditing('new')}>
            <Plus className="h-4 w-4" />
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

      <div className="overflow-hidden rounded-2xl border border-slate-200/60 bg-white shadow-sm">
        <DataTable
          table={table}
          columnsLength={columns.length}
          dataLength={templates.length}
          isLoading={isLoading}
          emptyIcon={<FileText className="h-8 w-8 opacity-50" />}
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
            <Button type="button" variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={remove.isPending}
            >
              {remove.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
