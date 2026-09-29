import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ClipboardList } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api';
import { truckGroupsApi } from '@/lib/truckGroups';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from '@/hooks/use-toast';

const KEY = ['trip-order-template'];

/**
 * The company's part of the order sheet posted to truck groups: the
 * "ОБЯЗАТЕЛЬНО К ИСПОЛНЕНИЮ" list and the dispatchers' phones. The rest of
 * the post comes from the trip itself.
 */
export function TripOrderTemplateCard() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'manager' || user?.role === 'superadmin';

  const { data } = useQuery({ queryKey: KEY, queryFn: truckGroupsApi.template });
  const [rules, setRules] = useState('');
  const [footer, setFooter] = useState('');

  useEffect(() => {
    if (!data) return;
    // Start from the built-in list rather than an empty box: most companies
    // only change a line or two.
    setRules(data.rules ?? data.default_rules);
    setFooter(data.footer ?? '');
  }, [data]);

  const save = useMutation({
    mutationFn: () => truckGroupsApi.saveTemplate({ rules, footer }),
    onSuccess: (saved) => {
      queryClient.setQueryData(KEY, saved);
      toast({ title: t('tripOrder.templateSaved') });
    },
    onError: (err) =>
      toast({
        title: t('tripOrder.failed'),
        description: err instanceof ApiError ? err.detail : String(err),
        variant: 'destructive',
      }),
  });

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClipboardList className="h-5 w-5" /> {t('tripOrder.templateTitle')}
        </CardTitle>
        <CardDescription>{t('tripOrder.templateDescription')}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="order-rules">{t('tripOrder.rules')}</Label>
            <Textarea
              id="order-rules"
              rows={10}
              maxLength={2000}
              disabled={!canEdit}
              value={rules}
              onChange={(e) => setRules(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t('tripOrder.rulesHint')}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="order-footer">{t('tripOrder.footer')}</Label>
            <Input
              id="order-footer"
              maxLength={500}
              disabled={!canEdit}
              placeholder="Узб +998 90 000 00 00 · коз +7 700 000 00 00 · росия +7 900 000 00 00"
              value={footer}
              onChange={(e) => setFooter(e.target.value)}
            />
          </div>
          {canEdit && (
            <Button type="submit" disabled={save.isPending}>
              {t('common.save')}
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
