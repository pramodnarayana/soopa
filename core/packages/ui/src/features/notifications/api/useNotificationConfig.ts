/**
 * API hooks for Notification Preferences (routing rules) and Templates.
 *
 * All mutations use React Query's useMutation with optimistic cache invalidation
 * for a snappy UI experience.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export interface NotificationPreference {
  id: string;
  tenant_id: string;
  event_type: string;
  channels: string[];
}

export interface NotificationTemplate {
  id: string;
  tenant_id: string;
  name: string;
  event_type: string;
  channel: string;
  subject_template: string | null;
  body_template: string;
  is_active: boolean;
}

export interface PreviewResult {
  rendered_subject: string | null;
  rendered_body: string;
}

export interface NotificationConfigContext {
  tenantId: string;
  accessToken: string;
  apiUrl: string;
}

function notificationBase(apiUrl: string, tenantId: string) {
  return `${apiUrl}/${tenantId}`;
}

function authHeader(token: string) {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

async function handleResponseError(res: Response, fallbackMessage: string): Promise<never> {
  const err = await res.json().catch(() => ({}));
  throw new Error((err as { detail?: string }).detail ?? fallbackMessage);
}

// ---------------------------------------------------------------------------
// Preferences
// ---------------------------------------------------------------------------

export function usePreferences({ tenantId, accessToken, apiUrl }: NotificationConfigContext) {
  return useQuery<NotificationPreference[]>({
    queryKey: ['notification-preferences', tenantId],
    queryFn: async () => {
      const res = await fetch(`${notificationBase(apiUrl, tenantId)}/preferences`, {
        headers: authHeader(accessToken),
      });
      if (!res.ok) await handleResponseError(res, 'Failed to fetch preferences');
      return res.json();
    },
  });
}

export function useUpsertPreference({ tenantId, accessToken, apiUrl }: NotificationConfigContext) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ event_type, channels }: { event_type: string; channels: string[] }) => {
      const res = await fetch(
        `${notificationBase(apiUrl, tenantId)}/preferences/${encodeURIComponent(event_type)}`,
        {
          method: 'PUT',
          headers: authHeader(accessToken),
          body: JSON.stringify({ channels }),
        },
      );
      if (!res.ok) await handleResponseError(res, 'Failed to save preference');
      return res.json() as Promise<NotificationPreference>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notification-preferences', tenantId] }),
  });
}

export function useDeletePreference({ tenantId, accessToken, apiUrl }: NotificationConfigContext) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (event_type: string) => {
      const res = await fetch(
        `${notificationBase(apiUrl, tenantId)}/preferences/${encodeURIComponent(event_type)}`,
        { method: 'DELETE', headers: authHeader(accessToken) },
      );
      if (!res.ok && res.status !== 204) throw new Error('Failed to delete preference');
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notification-preferences', tenantId] }),
  });
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

export function useTemplates({ tenantId, accessToken, apiUrl }: NotificationConfigContext) {
  return useQuery<NotificationTemplate[]>({
    queryKey: ['notification-templates', tenantId],
    queryFn: async () => {
      const res = await fetch(`${notificationBase(apiUrl, tenantId)}/templates`, {
        headers: authHeader(accessToken),
      });
      if (!res.ok) await handleResponseError(res, 'Failed to fetch templates');
      return res.json();
    },
  });
}

export function useUpsertTemplate({ tenantId, accessToken, apiUrl }: NotificationConfigContext) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Omit<NotificationTemplate, 'id' | 'tenant_id'>) => {
      const res = await fetch(`${notificationBase(apiUrl, tenantId)}/templates`, {
        method: 'PUT',
        headers: authHeader(accessToken),
        body: JSON.stringify(payload),
      });
      if (!res.ok) await handleResponseError(res, 'Failed to save template');
      return res.json() as Promise<NotificationTemplate>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notification-templates', tenantId] }),
  });
}

export function useDeleteTemplate({ tenantId, accessToken, apiUrl }: NotificationConfigContext) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (templateId: string) => {
      const res = await fetch(
        `${notificationBase(apiUrl, tenantId)}/templates/${encodeURIComponent(templateId)}`,
        {
          method: 'DELETE',
          headers: authHeader(accessToken),
        },
      );
      if (!res.ok && res.status !== 204) {
        await handleResponseError(res, 'Failed to delete template');
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notification-templates', tenantId] }),
  });
}

export function usePreviewTemplate({ tenantId, accessToken, apiUrl }: NotificationConfigContext) {
  return useMutation({
    mutationFn: async (payload: {
      body_template: string;
      subject_template?: string;
      mock_payload?: Record<string, unknown>;
    }) => {
      const res = await fetch(`${notificationBase(apiUrl, tenantId)}/templates/preview`, {
        method: 'POST',
        headers: authHeader(accessToken),
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? 'Preview failed');
      }
      return res.json() as Promise<PreviewResult>;
    },
  });
}
