/**
 * Dispatcher panel for cargo-owner Telegram subscriptions on one trip.
 *
 * The dispatcher enters a contact name/phone, gets back a magic ``t.me`` link,
 * and shares it with the cargo owner over any channel. Once the owner opens
 * the link the row flips to "activated" — the bot pins a map button in their
 * chat and sends event pushes (status changes) until they say /stop or the
 * dispatcher deletes the row. The morning digest starts off; the switch on
 * each row turns it on for a customer who still wants one.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Send, Trash2, MessageSquare, Check, Map as MapIcon, ExternalLink } from 'lucide-react';
import { formatDistanceToNow } from '@/lib/datetime';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { toast } from '@/hooks/use-toast';
import { tripSubscriptionsApi, type TripSubscription } from '@/lib/trips';
import { ApiError } from '@/lib/api';

interface Props {
  tripId: string;
}

export function TripSubscriptionsCard({ tripId }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [contactName, setContactName] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  // Which button last copied, as "<sub id>:<link kind>", so the tick lands on
  // the button that was pressed and not on its neighbour too.
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  function copyToClipboard(text: string, onDone: () => void): void {
    // Modern browsers only. Older-browser fallback isn't worth carrying — the
    // dashboard already requires a current Chrome/Edge/Firefox.
    navigator.clipboard.writeText(text).then(
      onDone,
      () => toast({ title: t('tripSubscriptions.copyFailedTitle'), variant: 'destructive' }),
    );
  }

  const listQuery = useQuery({
    queryKey: ['trip', tripId, 'subscriptions'],
    queryFn: () => tripSubscriptionsApi.list(tripId),
    // Newly activated subscriptions flip via the Telegram webhook, so poll
    // gently — the dispatcher wants to see "customer joined" within a minute.
    refetchInterval: 20_000,
    enabled: Boolean(tripId),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      tripSubscriptionsApi.create(tripId, {
        contactName: contactName.trim() || null,
        contactPhone: contactPhone.trim() || null,
      }),
    onSuccess: () => {
      setContactName('');
      setContactPhone('');
      queryClient.invalidateQueries({ queryKey: ['trip', tripId, 'subscriptions'] });
      toast({
        title: t('tripSubscriptions.createSuccessTitle'),
        description: t('tripSubscriptions.createSuccessDescription'),
      });
    },
    onError: (err) =>
      toast({
        title: t('tripSubscriptions.createErrorTitle'),
        description: err instanceof ApiError ? err.detail : String(err),
        variant: 'destructive',
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => tripSubscriptionsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trip', tripId, 'subscriptions'] });
      toast({ title: t('tripSubscriptions.deleteSuccessTitle') });
    },
    onError: (err) =>
      toast({
        title: t('tripSubscriptions.deleteErrorTitle'),
        description: err instanceof ApiError ? err.detail : String(err),
        variant: 'destructive',
      }),
  });

  const dailyMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      tripSubscriptionsApi.setDaily(id, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trip', tripId, 'subscriptions'] }),
    onError: (err) =>
      toast({
        title: t('tripSubscriptions.dailyUpdateErrorTitle'),
        description: err instanceof ApiError ? err.detail : String(err),
        variant: 'destructive',
      }),
  });

  const subscriptions = listQuery.data ?? [];

  const handleCopy = (sub: TripSubscription, kind: 'telegram' | 'map' = 'telegram') => {
    const link = kind === 'map' ? sub.trackUrl : sub.deepLink;
    if (!link) return;
    const key = `${sub.id}:${kind}`;
    copyToClipboard(link, () => {
      setCopiedId(key);
      window.setTimeout(() => setCopiedId((prev) => (prev === key ? null : prev)), 1500);
      toast({
        title: kind === 'map' ? t('tripSubscriptions.mapCopySuccessTitle') : t('tripSubscriptions.copySuccessTitle'),
      });
    });
  };

  const handleTelegramShare = (sub: TripSubscription) => {
    const text = encodeURIComponent(t('tripSubscriptions.shareText', { link: sub.deepLink }));
    window.open(`https://t.me/share/url?url=${encodeURIComponent(sub.deepLink)}&text=${text}`, '_blank');
  };

  const handleConfirmDelete = () => {
    if (pendingDeleteId) deleteMutation.mutate(pendingDeleteId);
    setPendingDeleteId(null);
  };

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <MessageSquare className="h-5 w-5" />
          {t('tripSubscriptions.title')}
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Create form */}
        <form
          className="grid gap-3 rounded-lg border border-dashed border-border/60 p-3 sm:grid-cols-[1fr_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            if (!createMutation.isPending) createMutation.mutate();
          }}
        >
          <div className="space-y-1">
            <Label htmlFor="sub-name" className="text-xs">
              {t('tripSubscriptions.nameLabel')}
            </Label>
            <Input
              id="sub-name"
              value={contactName}
              onChange={(e) => setContactName(e.target.value)}
              placeholder={t('tripSubscriptions.namePlaceholder')}
              maxLength={200}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="sub-phone" className="text-xs">
              {t('tripSubscriptions.phoneLabel')}
            </Label>
            <Input
              id="sub-phone"
              value={contactPhone}
              onChange={(e) => setContactPhone(e.target.value)}
              placeholder={t('tripSubscriptions.phonePlaceholder')}
              maxLength={40}
            />
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={createMutation.isPending} className="w-full sm:w-auto">
              {t('tripSubscriptions.createButton')}
            </Button>
          </div>
        </form>

        {/* List */}
        {listQuery.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : subscriptions.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t('tripSubscriptions.empty')}
          </p>
        ) : (
          <ul className="space-y-2">
            {subscriptions.map((sub) => (
              <li
                key={sub.id}
                className="flex flex-col gap-2 rounded-lg border border-border/50 bg-muted/40 p-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">
                      {sub.contactName || t('tripSubscriptions.unnamedContact')}
                    </span>
                    {sub.activated ? (
                      <Badge variant="default" className="gap-1">
                        <Check className="h-3 w-3" /> {t('tripSubscriptions.activeBadge')}
                      </Badge>
                    ) : (
                      <Badge variant="outline">{t('tripSubscriptions.pendingBadge')}</Badge>
                    )}
                  </div>
                  {sub.contactPhone && (
                    <p className="text-xs text-muted-foreground">{sub.contactPhone}</p>
                  )}
                  {sub.activatedAt && (
                    <p className="text-xs text-muted-foreground">
                      {t('tripSubscriptions.connectedAt')}{' '}
                      {formatDistanceToNow(new Date(sub.activatedAt), { addSuffix: true })}
                    </p>
                  )}
                  <p className="truncate text-xs text-muted-foreground" title={sub.deepLink}>
                    {sub.deepLink}
                  </p>
                  {/* The live map itself, for a customer reached by phone or
                      WhatsApp who will never open the bot. */}
                  {sub.trackUrl && (
                    <div className="flex min-w-0 items-center gap-1 text-xs">
                      <MapIcon className="h-3 w-3 shrink-0 text-primary" />
                      <a
                        href={sub.trackUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="truncate text-primary hover:underline"
                        title={sub.trackUrl}
                      >
                        {sub.trackUrl}
                      </a>
                      <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-1">
                  <label className="mr-2 flex items-center gap-2 text-xs text-muted-foreground">
                    <Switch
                      checked={sub.dailyEnabled}
                      disabled={dailyMutation.isPending}
                      onCheckedChange={(enabled) => dailyMutation.mutate({ id: sub.id, enabled })}
                    />
                    {t('tripSubscriptions.dailyLabel')}
                  </label>
                  {sub.trackUrl && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleCopy(sub, 'map')}
                      aria-label={t('tripSubscriptions.mapCopyAriaLabel')}
                      title={t('tripSubscriptions.mapCopyAriaLabel')}
                    >
                      {copiedId === `${sub.id}:map` ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        <MapIcon className="h-4 w-4" />
                      )}
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleCopy(sub)}
                    aria-label={t('tripSubscriptions.copyAriaLabel')}
                    title={t('tripSubscriptions.copyAriaLabel')}
                  >
                    {copiedId === `${sub.id}:telegram` ? (
                      <Check className="h-4 w-4" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleTelegramShare(sub)}
                    aria-label={t('tripSubscriptions.shareAriaLabel')}
                  >
                    <Send className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={deleteMutation.isPending}
                    onClick={() => setPendingDeleteId(sub.id)}
                    aria-label={t('tripSubscriptions.deleteAriaLabel')}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <AlertDialog open={pendingDeleteId !== null} onOpenChange={(open) => !open && setPendingDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('tripSubscriptions.confirmDeleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('tripSubscriptions.confirmDeleteDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('tripSubscriptions.confirmDeleteCancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmDelete}>
              {t('tripSubscriptions.confirmDeleteConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
