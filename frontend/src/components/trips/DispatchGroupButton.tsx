import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Link2Off, MessagesSquare, RefreshCw, Send } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ApiError } from '@/lib/api';
import { fleetBoardApi, type DispatchGroup } from '@/lib/fleetBoard';
import { toast } from '@/hooks/use-toast';

const KEY = ['dispatch-group'] as const;
// While a link is pending the dispatcher is in Telegram adding the bot; poll
// so the status turns "linked" without a reload when they come back.
const PENDING_POLL_MS = 5_000;

/**
 * The dispatchers' Telegram group the fleet board is posted to each morning.
 * Picked in Telegram, like a truck's group: the link opens the "add to group"
 * picker, and whichever group the bot joins through it is bound.
 */
export function DispatchGroupButton() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: KEY,
    queryFn: fleetBoardApi.group,
    refetchInterval: (q) => (q.state.data?.status === 'pending' ? PENDING_POLL_MS : false),
  });
  const status = data?.status ?? 'none';

  const onError = (err: unknown) =>
    toast({
      title: t('fleetBoard.group.failed'),
      description: err instanceof ApiError ? err.detail : String(err),
      variant: 'destructive',
    });
  const setData = (group: DispatchGroup) => queryClient.setQueryData(KEY, group);

  const link = useMutation({
    mutationFn: fleetBoardApi.linkGroup,
    onSuccess: (group) => {
      setData(group);
      if (group.deep_link) window.open(group.deep_link, '_blank', 'noopener');
    },
    onError,
  });
  const unlink = useMutation({ mutationFn: fleetBoardApi.unlinkGroup, onSuccess: setData, onError });
  const send = useMutation({
    mutationFn: fleetBoardApi.sendNow,
    onSuccess: (group) => {
      setData(group);
      toast({ title: t('fleetBoard.group.sent') });
    },
    onError,
  });

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" className="gap-2">
          <MessagesSquare className="h-4 w-4" />
          {t('fleetBoard.group.button')}
          {status === 'linked' && <span className="h-2 w-2 rounded-full bg-status-moving" />}
          {status === 'lost' && <span className="h-2 w-2 rounded-full bg-destructive" />}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 space-y-3">
        <div className="flex items-center gap-2">
          <p className="font-medium">{t('fleetBoard.group.title')}</p>
          {status === 'linked' && <Badge className="ml-auto">{t('fleetBoard.group.linked')}</Badge>}
          {status === 'lost' && (
            <Badge variant="destructive" className="ml-auto">
              {t('fleetBoard.group.lost')}
            </Badge>
          )}
        </div>

        <div className="space-y-1 text-sm">
          {status === 'none' && <p className="text-muted-foreground">{t('fleetBoard.group.noneHint')}</p>}
          {status === 'pending' && (
            <>
              <p className="text-muted-foreground">{t('fleetBoard.group.pendingHint')}</p>
              {data?.deep_link && (
                <a
                  href={data.deep_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 break-all text-primary hover:underline"
                >
                  <ExternalLink className="h-3.5 w-3.5 shrink-0" /> {data.deep_link}
                </a>
              )}
            </>
          )}
          {(status === 'linked' || status === 'lost') && (
            <>
              <p className="font-medium">{data?.chat_title || '—'}</p>
              <p className="text-xs text-muted-foreground">
                {status === 'lost'
                  ? t('fleetBoard.group.lostHint')
                  : data?.board_sent_on &&
                    t('fleetBoard.group.sentOn', { day: data.board_sent_on.split('-').reverse().join('.') })}
              </p>
            </>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {status === 'linked' && (
            <Button size="sm" onClick={() => send.mutate()} disabled={send.isPending}>
              <Send className="mr-2 h-4 w-4" /> {t('fleetBoard.group.sendNow')}
            </Button>
          )}
          <Button
            size="sm"
            variant={status === 'linked' ? 'outline' : 'default'}
            onClick={() => link.mutate()}
            disabled={link.isPending}
          >
            {status === 'none' ? (
              <MessagesSquare className="mr-2 h-4 w-4" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            {status === 'none' ? t('fleetBoard.group.link') : t('fleetBoard.group.relink')}
          </Button>
          {status !== 'none' && (
            <Button size="sm" variant="ghost" onClick={() => unlink.mutate()} disabled={unlink.isPending}>
              <Link2Off className="mr-2 h-4 w-4" /> {t('fleetBoard.group.unlink')}
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
