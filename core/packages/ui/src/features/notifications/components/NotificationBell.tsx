import { formatDistanceToNow } from 'date-fns';
import { Bell, Check, Clock } from 'lucide-react';
import React from 'react';
import { Popover, PopoverContent, PopoverTrigger } from '../../../components/ui/popover';
import {
  NotificationContext,
  useMarkNotificationAsRead,
  useNotifications,
} from '../api/useNotifications';

export const NotificationBell: React.FC<NotificationContext> = (props) => {
  const { data: notifications = [], isLoading, error } = useNotifications(props);
  const markAsRead = useMarkNotificationAsRead(props);

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const handleMarkAsRead = (id: string) => {
    markAsRead.mutate(id);
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return formatDistanceToNow(date, { addSuffix: true });
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="relative p-2 rounded-full hover:bg-slate-100 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-300"
          aria-label="Notifications"
        >
          <Bell className="w-5 h-5 text-slate-600" />
          {unreadCount > 0 && (
            <span className="absolute top-1 right-1 flex items-center justify-center w-4 h-4 text-[10px] font-bold text-white bg-red-500 rounded-full animate-in fade-in zoom-in duration-300">
              {unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0 overflow-hidden shadow-lg border-slate-200">
        <div className="bg-slate-50 px-4 py-3 border-b border-slate-200 flex justify-between items-center">
          <h3 className="text-sm font-semibold text-slate-800">Notifications</h3>
          {unreadCount > 0 && (
            <span className="text-xs font-medium text-slate-500 bg-slate-200 px-2 py-0.5 rounded-full">
              {unreadCount} New
            </span>
          )}
        </div>
        <div className="max-h-[300px] overflow-y-auto">
          {isLoading ? (
            <div className="flex justify-center items-center py-8">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-600"></div>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center py-10 text-red-500">
              <Bell className="w-10 h-10 mb-2 opacity-20" />
              <p className="text-sm">Failed to load notifications</p>
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-slate-500">
              <Bell className="w-10 h-10 mb-2 opacity-20" />
              <p className="text-sm">No new notifications</p>
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {notifications.map((notification) => (
                <li
                  key={notification.id}
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
                      <p className="text-xs text-slate-500 mt-1 line-clamp-2 leading-relaxed">
                        {notification.body}
                      </p>
                      <div className="flex items-center gap-1 mt-2 text-[10px] text-slate-400 font-medium">
                        <Clock className="w-3 h-3" />
                        {formatDate(notification.created_at)}
                      </div>
                    </div>
                    {!notification.is_read && (
                      <button
                        onClick={() => handleMarkAsRead(notification.id)}
                        className="text-blue-600 hover:text-blue-800 p-1 rounded hover:bg-blue-100 transition-colors"
                        title="Mark as read"
                      >
                        <Check className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
};
