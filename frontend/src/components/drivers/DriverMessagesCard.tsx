import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellRing, Check, CheckCheck, Inbox, Send } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api';
import { formatDistanceToNow } from '@/lib/datetime';
import { driverMessagesApi, type DriverMessage } from '@/lib/driverMessages';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';

const MAX_LENGTH = 1000;

/**
 * Ready-made texts for what dispatchers send most. They follow the panel's
 * language, and the dispatcher can edit them before sending: the phone shows
 * exactly what is in the box.
 */
const TEMPLATE_KEYS = ['gpsOn', 'callOffice', 'openApp'] as const;

function DeliveryState({ message }: { message: DriverMessage }) {
  const { t } = useTranslation();
  if (message.read_at) {
    return (
      <span className="flex items-center gap-1 text-xs text-status-moving">
        <CheckCheck className="h-3.5 w-3.5" /> {t('driverMessages.read')}
      </span>
    );
  }
  if (message.devices_delivered > 0) {
    return (
      <span className="flex items-center gap-1 text-xs text-muted-foreground">
        <Check className="h-3.5 w-3.5" /> {t('driverMessages.delivered')}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-status-stopped">
      <Inbox className="h-3.5 w-3.5" /> {t('driverMessages.inboxOnly')}
    </span>
  );
}

export function DriverMessagesCard({ driverId }: { driverId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [body, setBody] = useState('');

  const { data: messages = [] } = useQuery({
    queryKey: ['driver-messages', driverId],
    queryFn: () => driverMessagesApi.list(driverId),
    enabled: Boolean(driverId),
  });

  const sendMutation = useMutation({
    mutationFn: () => driverMessagesApi.send(driverId, { body: body.trim() }),
    onSuccess: (sent) => {
      setBody('');
      queryClient.invalidateQueries({ queryKey: ['driver-messages', driverId] });
      toast({
        title: t('driverMessages.sent'),
        description: sent.devices_delivered > 0 ? undefined : t('driverMessages.noDeviceHint'),
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
    <Card className="border-border/50 bg-card md:col-span-2">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <BellRing className="h-5 w-5" /> {t('driverMessages.title')}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend) sendMutation.mutate();
          }}
        >
          <div className="flex flex-wrap gap-2">
            {TEMPLATE_KEYS.map((key) => (
              <Button
                key={key}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setBody(t(`driverMessages.templates.${key}.text`))}
              >
                {t(`driverMessages.templates.${key}.label`)}
              </Button>
            ))}
          </div>
          <Textarea
            value={body}
            maxLength={MAX_LENGTH}
            rows={3}
            placeholder={t('driverMessages.placeholder')}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">
              {body.length}/{MAX_LENGTH}
            </span>
            <Button type="submit" disabled={!canSend}>
              <Send className="mr-2 h-4 w-4" /> {t('driverMessages.send')}
            </Button>
          </div>
        </form>

        {messages.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            {t('driverMessages.empty')}
          </p>
        ) : (
          <div className="divide-y divide-border/50">
            {messages.slice(0, 10).map((m) => (
              <div key={m.id} className="space-y-1 py-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{m.title}</span>
                    {m.kind === 'gps_silent' && (
                      <Badge variant="outline" className={cn('text-xs')}>
                        {t('driverMessages.auto')}
                      </Badge>
                    )}
                  </div>
                  <DeliveryState message={m} />
                </div>
                <p className="whitespace-pre-wrap text-muted-foreground">{m.body}</p>
                <p className="text-xs text-muted-foreground">
                  {formatDistanceToNow(new Date(m.created_at), { addSuffix: true })}
                </p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
