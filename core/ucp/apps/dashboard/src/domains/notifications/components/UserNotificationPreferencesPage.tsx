import { Switch, usePreferences } from '@soopa/ui';
import { SlidersHorizontal } from 'lucide-react';
import React from 'react';
import { toast } from 'sonner';
import { useTenantContext } from '@/contexts/TenantContext';
import { getApiUrl } from '@/lib/config';
import { useUpdateUserPreference, useUserPreferences } from '../api/useUserNotificationPreferences';

export const UserNotificationPreferencesPage: React.FC = () => {
  const { tenantId, token } = useTenantContext();

  // We need to fetch the tenant-level routes to know WHICH event_types are available,
  // then we fetch the user's specific preferences to know what they toggled.
  const { data: tenantRules = [], isLoading: isLoadingRules } = usePreferences({
    tenantId: tenantId,
    accessToken: token,
    apiUrl: getApiUrl('/api/v1/notifications'),
  });
  const { data: userPrefs = [], isLoading: isLoadingPrefs } = useUserPreferences();
  const updatePreference = useUpdateUserPreference();

  const isLoading = isLoadingRules || isLoadingPrefs;

  // Group rules by event type
  const eventTypes = Array.from(new Set(tenantRules.map((r) => r.event_type)));

  const handleToggle = (eventType: string, channel: string, currentEnabled: boolean) => {
    updatePreference.mutate(
      { eventType, channel, isEnabled: !currentEnabled },
      {
        onSuccess: () => {
          toast.success(`Preference for ${channel} updated`);
        },
        onError: () => {
          toast.error('Failed to update preference');
        },
      },
    );
  };

  const isChannelEnabled = (eventType: string, channel: string) => {
    const pref = userPrefs.find((p) => p.event_type === eventType && p.channel === channel);
    // Default is opt-out, meaning if there's no record, it's enabled.
    return pref ? pref.is_enabled : true;
  };

  if (isLoading) {
    return <div className="p-8 text-slate-500">Loading preferences...</div>;
  }

  return (
    <div className="flex flex-col gap-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700 ease-out">
      <section className="flex flex-col gap-2 pb-6 border-b border-slate-200/60">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
            <SlidersHorizontal className="w-8 h-8 text-indigo-600" />
            My Notification Preferences
          </h2>
          <p className="text-slate-500 text-sm mt-1">
            Choose how you want to be notified for different events.
          </p>
        </div>
      </section>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200/60 overflow-hidden">
        {eventTypes.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            No notifications are currently configured for this workspace.
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {eventTypes.map((eventType) => {
              const rule = tenantRules.find((r) => r.event_type === eventType);
              if (!rule) return null;

              return (
                <div
                  key={eventType}
                  className="p-6 flex flex-col md:flex-row md:items-center justify-between gap-6"
                >
                  <div>
                    <h3 className="text-base font-semibold text-slate-900">{eventType}</h3>
                    <p className="text-sm text-slate-500 mt-1">
                      Available channels: {rule.channels.join(', ')}
                    </p>
                  </div>
                  <div className="flex gap-6">
                    {rule.channels.map((channel) => {
                      const enabled = isChannelEnabled(eventType, channel);
                      return (
                        <div key={channel} className="flex items-center gap-3">
                          <label className="text-sm font-medium text-slate-700">{channel}</label>
                          <Switch
                            checked={enabled}
                            onCheckedChange={() => handleToggle(eventType, channel, enabled)}
                            disabled={updatePreference.isPending}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
