import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';

import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { listQueue, refreshQueue, type QueueRow, type QueueStatus } from '@/lib/queue';
import { ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';

const QUEUE_KEY = ['queue'] as const;

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

// Maps a normalized CarGoRuqsat status to a badge variant + i18n label key.
const STATUS_META: Record<QueueStatus, { variant: BadgeProps['variant']; labelKey: string }> = {
  in_queue: { variant: 'default', labelKey: 'queue.statusInQueue' },
  late: { variant: 'destructive', labelKey: 'queue.statusLate' },
  crossed: { variant: 'secondary', labelKey: 'queue.statusCrossed' },
  check_failed: { variant: 'destructive', labelKey: 'queue.statusCheckFailed' },
  revoked: { variant: 'destructive', labelKey: 'queue.statusRevoked' },
  none: { variant: 'outline', labelKey: 'queue.statusNone' },
  unknown: { variant: 'outline', labelKey: 'queue.statusUnknown' },
};

function formatDateTime(value: Date | null): string {
  if (!value) return '—';
  return value.toLocaleString();
}

export default function BorderQueuePage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: rows = [], isLoading } = useQuery({
    queryKey: QUEUE_KEY,
    queryFn: listQueue,
    refetchInterval: 60_000,
  });

  const refreshMutation = useMutation({
    mutationFn: refreshQueue,
    onSuccess: (fresh) => {
      queryClient.setQueryData<QueueRow[]>(QUEUE_KEY, fresh);
      toast({ title: t('queue.refreshed') });
    },
    onError: (err) =>
      toast({
        title: t('queue.refreshFailed'),
        description: describeError(err, ''),
        variant: 'destructive',
      }),
  });

  const renderStatus = (status: QueueStatus | null) => {
    const meta = STATUS_META[status ?? 'unknown'];
    return <Badge variant={meta.variant}>{t(meta.labelKey)}</Badge>;
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('queue.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('queue.subtitle')}</p>
        </div>
        <Button onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
          <RefreshCw className={`mr-2 h-4 w-4 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
          {t('queue.refresh')}
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('queue.driver')}</TableHead>
              <TableHead>{t('queue.plate')}</TableHead>
              <TableHead>{t('queue.checkpoint')}</TableHead>
              <TableHead>{t('queue.country')}</TableHead>
              <TableHead>{t('queue.status')}</TableHead>
              <TableHead>{t('queue.lastSeen')}</TableHead>
              <TableHead>{t('queue.updated')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {!isLoading && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  {t('queue.empty')}
                </TableCell>
              </TableRow>
            )}
            {rows.map((row) => (
              <TableRow key={row.watchId}>
                <TableCell className="font-medium">{row.driverName}</TableCell>
                <TableCell className="font-mono text-xs">{row.plate}</TableCell>
                <TableCell>{row.checkpoint}</TableCell>
                <TableCell>{row.country ?? '—'}</TableCell>
                <TableCell>{renderStatus(row.lastStatus)}</TableCell>
                <TableCell>{formatDateTime(row.lastSeenQueueAt)}</TableCell>
                <TableCell>{formatDateTime(row.updatedAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
