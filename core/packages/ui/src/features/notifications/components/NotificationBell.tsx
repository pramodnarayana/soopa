import { formatDistanceToNow } from 'date-fns';
import { Bell, Check, Clock } from 'lucide-react';
import React from 'react';
import { toast } from 'sonner';
import { Button } from '../../../components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '../../../components/ui/popover';
import {
  type InAppNotification,
  type NotificationContext,
  useMarkNotificationAsRead,
  useNotifications,
} from '../api/useNotifications';

function formatRelativeDate(dateString: string): string {
  return formatDistanceToNow(new Date(dateString), { addSuffix: true });
}

function NotificationBellItem({
  notification,
  onMarkAsRead,
}: {
  readonly notification: InAppNotification;
  readonly onMarkAsRead: (id: string) => void;
}) {
  return (
    <li
      className={`p-4 transition-colors hover:bg-slate-50 ${
        !notification.is_read ? 'bg-blue-50/50' : ''
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <p
            className={`text-sm ${
              !notification.is_read ? 'font-semibold text-slate-900' : 'text-slate-700'
            }`}
          >
            {notification.title}
          </p>
          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-500">
            {notification.body}
          </p>
          <div className="mt-2 flex items-center gap-1 text-xs font-medium text-slate-400">
            <Clock className="h-3 w-3" />
            {formatRelativeDate(notification.created_at)}
          </div>
        </div>
        {!notification.is_read && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onMarkAsRead(notification.id)}
            className="h-7 w-7 text-blue-600 hover:bg-blue-100 hover:text-blue-800"
            title="Mark as read"
            aria-label="Mark as read"
          >
            <Check className="h-4 w-4" />
          </Button>
        )}
      </div>
    </li>
  );
}

export const NotificationBell: React.FC<NotificationContext> = (props) => {
  const { data: notifications = [], isLoading, isError } = useNotifications(props);
  const markAsRead = useMarkNotificationAsRead(props);

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const handleMarkAsRead = (id: string): void => {
    markAsRead.mutate(id, {
      onSuccess: (result) => {
        if (!result.ok) {
          toast.error(result.error.message || 'Failed to mark notification as read');
        }
      },
    });
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="relative rounded-full hover:bg-slate-100"
          aria-label="Notifications"
        >
          <Bell className="h-5 w-5 text-slate-600" />
          {unreadCount > 0 && (
            <span className="animate-in fade-in zoom-in absolute top-0.5 right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-xs font-bold text-white duration-300">
              {unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 overflow-hidden border-slate-200 p-0 shadow-lg">
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-800">Notifications</h3>
          {unreadCount > 0 && (
            <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-500">
              {unreadCount} New
            </span>
          )}
        </div>
        <div className="max-h-72 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-indigo-600" />
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center justify-center py-10 text-red-500">
              <Bell className="mb-2 h-10 w-10 opacity-20" />
              <p className="text-sm">Failed to load notifications</p>
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-slate-500">
              <Bell className="mb-2 h-10 w-10 opacity-20" />
              <p className="text-sm">No new notifications</p>
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {notifications.map((notification) => (
                <NotificationBellItem
                  key={notification.id}
                  notification={notification}
                  onMarkAsRead={handleMarkAsRead}
                />
              ))}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
};
