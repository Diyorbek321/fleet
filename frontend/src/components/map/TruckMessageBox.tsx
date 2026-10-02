import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Send, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api';
import { driverMessagesApi } from '@/lib/driverMessages';
import { toast } from '@/hooks/use-toast';

const MAX_LENGTH = 1000;

interface TruckMessageBoxProps {
  driverId: string;
  driverName: string;
}

/**
 * A message to the driver of the truck picked on the map. The dispatcher is
 * looking at the lorry when they decide to write — "you have stopped, call
 * the office" — so the box sits on the map rather than two pages away on the
 * driver's card. Same endpoint as that card: the push goes to the phone and
 * the text waits in the app's inbox.
 */
export function TruckMessageBox({ driverId, driverName }: TruckMessageBoxProps) {
  const { t } = useTranslation();
  const [body, setBody] = useState('');

  const sendMutation = useMutation({
    mutationFn: () => driverMessagesApi.send(driverId, { body: body.trim() }),
    onSuccess: (sent) => {
      setBody('');
      toast({
        title: t('driverMessages.sent'),
        description: sent.devices_delivered > 0 ? driverName : t('driverMessages.noDeviceHint'),
      });
    },
    onError: (err) =>
      toast({
        title: t('driverMessages.sendFailed'),
        description: err instanceof ApiError ? err.detail : String(err),
        variant: 'destructive',
      }),
  });

  const canSend = body.trim().length > 0 && !sendMutation.isPending;

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) sendMutation.mutate();
      }}
    >
      <Textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder={t('driverMessages.placeholder')}
        maxLength={MAX_LENGTH}
        rows={3}
        className="resize-none bg-secondary/50 border-0 text-sm"
        onKeyDown={(e) => {
          // Ctrl/⌘+Enter sends; a plain Enter is a new line in the message.
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && canSend) {
            e.preventDefault();
            sendMutation.mutate();
          }
        }}
      />
      <Button type="submit" size="sm" className="w-full" disabled={!canSend}>
        {sendMutation.isPending ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <Send className="mr-2 h-4 w-4" />
        )}
        {t('driverMessages.send')}
      </Button>
    </form>
  );
}
