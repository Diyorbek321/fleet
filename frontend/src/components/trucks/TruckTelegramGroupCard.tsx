import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, Link2Off, MessagesSquare, RefreshCw } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api';
import { formatDistanceToNow } from '@/lib/datetime';
import { truckGroupsApi, type TruckGroup } from '@/lib/truckGroups';
import { toast } from '@/hooks/use-toast';

// While a link is pending the dispatcher is in Telegram adding the bot; poll
// so the card turns "linked" without a reload when they come back.
const PENDING_POLL_MS = 5_000;

/**
 * Which Telegram group this truck's new orders are posted to.
 *
 * The group is picked in Telegram, not here: the link opens the "add to
 * group" picker, and whichever group the bot joins through it is bound.
 */
export function TruckTelegramGroupCard({ truckId }: { truckId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ['truck-group', truckId];

  const { data } = useQuery({
    queryKey: key,
    queryFn: () => truckGroupsApi.get(truckId),
    refetchInterval: (q) => (q.state.data?.status === 'pending' ? PENDING_POLL_MS : false),
  });

  const onError = (err: unknown) =>
    toast({
      title: t('truckGroup.failed'),
      description: err instanceof ApiError ? err.detail : String(err),
      variant: 'destructive',
    });
  const setData = (group: TruckGroup) => queryClient.setQueryData(key, group);

  const link = useMutation({
    mutationFn: () => truckGroupsApi.link(truckId),
    onSuccess: (group) => {
      setData(group);
      if (group.deep_link) window.open(group.deep_link, '_blank', 'noopener');
    },
    onError,
  });
  const unlink = useMutation({
    mutationFn: () => truckGroupsApi.unlink(truckId),
    onSuccess: setData,
    onError,
  });

  const status = data?.status ?? 'none';

  return (
    <Card className="border-border/50 bg-card md:col-span-2">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <MessagesSquare className="h-5 w-5" /> {t('truckGroup.title')}
          {status === 'linked' && <Badge className="ml-auto">{t('truckGroup.linked')}</Badge>}
          {status === 'lost' && (
            <Badge variant="destructive" className="ml-auto">
              {t('truckGroup.lost')}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1 text-sm">
          {status === 'none' && <p className="text-muted-foreground">{t('truckGroup.noneHint')}</p>}
          {status === 'pending' && (
            <>
              <p className="text-muted-foreground">{t('truckGroup.pendingHint')}</p>
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
                  ? t('truckGroup.lostHint')
                  : data?.activated_at &&
                    t('truckGroup.since', {
                      ago: formatDistanceToNow(new Date(data.activated_at), { addSuffix: true }),
                    })}
              </p>
            </>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          {status !== 'none' && (
            <Button variant="outline" onClick={() => unlink.mutate()} disabled={unlink.isPending}>
              <Link2Off className="mr-2 h-4 w-4" /> {t('truckGroup.unlink')}
            </Button>
          )}
          <Button onClick={() => link.mutate()} disabled={link.isPending}>
            {status === 'none' ? (
              <MessagesSquare className="mr-2 h-4 w-4" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            {status === 'none' ? t('truckGroup.link') : t('truckGroup.relink')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
