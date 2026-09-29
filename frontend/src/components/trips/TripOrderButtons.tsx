import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardList, Send } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api';
import { truckGroupsApi } from '@/lib/truckGroups';
import { toast } from '@/hooks/use-toast';

/**
 * The order sheet ("заявка") as the truck's group gets it: copy it for a
 * chat that is not linked, or post it to the group again.
 */
export function TripOrderButtons({ tripId, hasTruck }: { tripId: string; hasTruck: boolean }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<'copy' | 'send' | null>(null);

  const fail = (err: unknown) =>
    toast({
      title: t('tripOrder.failed'),
      description: err instanceof ApiError ? err.detail : String(err),
      variant: 'destructive',
    });

  const copy = async () => {
    setBusy('copy');
    try {
      const { text } = await truckGroupsApi.orderText(tripId);
      try {
        await navigator.clipboard.writeText(text);
        toast({ title: t('tripOrder.copied') });
      } catch {
        window.prompt(t('trips.copyManually'), text);
      }
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const send = async () => {
    setBusy('send');
    try {
      const { sent_at } = await truckGroupsApi.orderText(tripId);
      // Already posted once: a second post is a real message in a real
      // group, so it is asked for, not assumed.
      if (sent_at && !window.confirm(t('tripOrder.confirmResend'))) return;
      await truckGroupsApi.sendOrder(tripId);
      toast({ title: t('tripOrder.sent') });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Button variant="outline" size="sm" onClick={copy} disabled={busy !== null}>
        <ClipboardList className="mr-2 h-4 w-4" /> {t('tripOrder.copy')}
      </Button>
      {hasTruck && (
        <Button variant="outline" size="sm" onClick={send} disabled={busy !== null}>
          <Send className="mr-2 h-4 w-4" /> {t('tripOrder.send')}
        </Button>
      )}
    </>
  );
}
