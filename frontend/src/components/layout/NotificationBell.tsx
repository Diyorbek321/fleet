import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { formatDistanceToNow } from '@/lib/datetime';
import {
  NOTIFICATIONS_KEY,
  notificationsApi,
  type NotificationFeed,
  type PanelNotification,
} from '@/lib/notifications';
import { cn } from '@/lib/utils';

// The WebSocket says when something new arrives; this only covers a dropped
// socket, so it can be slow.
const POLL_MS = 60_000;

const severityDot: Record<PanelNotification['severity'], string> = {
  critical: 'bg-destructive',
  warning: 'bg-status-stopped',
  info: 'bg-primary',
};

export function NotificationBell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // What was unread at the moment the bell was opened. Opening marks
  // everything seen on the server, but the entries the user came to look at
  // should stay highlighted while the menu is open.
  const [unreadSince, setUnreadSince] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: notificationsApi.feed,
    refetchInterval: POLL_MS,
  });

  const seenMutation = useMutation({
    mutationFn: notificationsApi.markSeen,
    onSuccess: (feed) => queryClient.setQueryData<NotificationFeed>(NOTIFICATIONS_KEY, feed),
  });

  const items = data?.items ?? [];
  const unreadCount = data?.unread_count ?? 0;

  const onOpenChange = (open: boolean) => {
    if (!open) {
      setUnreadSince(null);
      return;
    }
    setUnreadSince(data?.seen_at ?? null);
    if (unreadCount > 0) seenMutation.mutate();
  };

  const isUnread = (n: PanelNotification) =>
    unreadSince !== null && new Date(n.created_at) > new Date(unreadSince);

  return (
    <DropdownMenu onOpenChange={onOpenChange}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={t('notifications.title')}
        >
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && (
            <Badge
              variant="destructive"
              className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full p-0 px-1 text-xs"
            >
              {unreadCount > 99 ? '99+' : unreadCount}
            </Badge>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-96 max-w-[calc(100vw-2rem)] bg-popover">
        <DropdownMenuLabel className="font-semibold">{t('notifications.title')}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="max-h-[420px] overflow-y-auto">
          {items.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-8 text-center">
              <Bell className="h-6 w-6 text-muted-foreground/60" />
              <p className="text-sm text-muted-foreground">{t('notifications.empty')}</p>
            </div>
          ) : (
            items.map((n) => (
              <DropdownMenuItem
                key={n.id}
                className={cn(
                  'flex cursor-pointer flex-col items-start gap-1 p-3',
                  isUnread(n) && 'bg-primary/5',
                )}
                onSelect={() => n.path && navigate(n.path)}
              >
                <div className="flex w-full items-start gap-2">
                  <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', severityDot[n.severity])} />
                  <span className="text-sm font-medium">{n.title}</span>
                </div>
                {n.body && (
                  <p className="whitespace-pre-line pl-4 text-xs text-muted-foreground">{n.body}</p>
                )}
                <span className="pl-4 text-xs text-muted-foreground/70">
                  {t(`telegramAlerts.kinds.${n.kind}`, { defaultValue: '' })}
                  {' · '}
                  {formatDistanceToNow(new Date(n.created_at), { addSuffix: true })}
                </span>
              </DropdownMenuItem>
            ))
          )}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
