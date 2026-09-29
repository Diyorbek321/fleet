import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy } from 'lucide-react';

import { Button, type ButtonProps } from '@/components/ui/button';
import { tripsApi } from '@/lib/trips';
import { ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';

interface Props {
  tripId: string;
  size?: ButtonProps['size'];
  variant?: ButtonProps['variant'];
  /** Icon only — the trips list has no room for a label. */
  iconOnly?: boolean;
}

/**
 * Copies the trip's status — the cargo owner's card, as plain text — so the
 * dispatcher can paste it into whatever chat the customer asked in.
 *
 * The text is built on the server by the same code as the Telegram message,
 * so the two never say different things about one load.
 */
export function CopyTripStatusButton({ tripId, size = 'sm', variant = 'outline', iconOnly }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    setBusy(true);
    let text: string;
    try {
      text = await tripsApi.card(tripId);
    } catch (err) {
      toast({
        title: t('trips.copyFailed'),
        description: err instanceof ApiError ? err.detail : err instanceof Error ? err.message : '',
        variant: 'destructive',
      });
      setBusy(false);
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
      toast({ title: t('trips.statusCopied') });
    } catch {
      // The clipboard can refuse (an insecure origin, a lost user gesture);
      // the text is still worth handing over for a manual copy.
      window.prompt(t('trips.copyManually'), text);
    } finally {
      setBusy(false);
    }
  };

  const Icon = copied ? Check : Copy;
  return (
    <Button
      type="button"
      size={iconOnly ? 'icon' : size}
      variant={variant}
      disabled={busy}
      title={t('trips.copyStatus')}
      onClick={(e) => {
        e.stopPropagation();
        void copy();
      }}
    >
      <Icon className={iconOnly ? 'h-4 w-4' : 'mr-2 h-4 w-4'} />
      {!iconOnly && t('trips.copyStatus')}
    </Button>
  );
}
