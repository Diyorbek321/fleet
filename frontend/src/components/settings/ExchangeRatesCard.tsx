import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Coins, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api';
import { orgSettingsApi, type OrgSettingsInput } from '@/lib/orgSettings';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from '@/hooks/use-toast';

const FIELDS = [
  { key: 'usd_to_kzt', currency: 'KZT', labelKey: 'settings.rates.kzt' },
  { key: 'usd_to_rub', currency: 'RUB', labelKey: 'settings.rates.rub' },
  { key: 'usd_to_uzs', currency: 'UZS', labelKey: 'settings.rates.uzs' },
] as const;

type FieldKey = (typeof FIELDS)[number]['key'];

/**
 * The company's fallback exchange rates.
 *
 * The country-expense report needs one number to compare tenge, roubles and
 * so'm against, and most of the time it takes that from the trip itself — the
 * driver wrote down what he handed over and what he got back. These fill the
 * gaps: the Uzbek leg always (no exchange is recorded for it) and any trip
 * where the exchange rows were left blank.
 *
 * Empty is a valid state, not an unfinished one. With no rate the report shows
 * tenge as tenge and says the USD column is unavailable, which is honest; a
 * pre-filled "sensible" default would convert every past trip at a rate nobody
 * chose and go stale in a month without anyone noticing.
 */
export function ExchangeRatesCard() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'superadmin';

  const { data, isLoading } = useQuery({
    queryKey: ['org', 'settings'],
    queryFn: orgSettingsApi.get,
  });

  const [draft, setDraft] = useState<Record<FieldKey, string>>({
    usd_to_kzt: '',
    usd_to_rub: '',
    usd_to_uzs: '',
  });

  useEffect(() => {
    if (!data) return;
    setDraft({
      usd_to_kzt: data.usd_to_kzt?.toString() ?? '',
      usd_to_rub: data.usd_to_rub?.toString() ?? '',
      usd_to_uzs: data.usd_to_uzs?.toString() ?? '',
    });
  }, [data]);

  const save = useMutation({
    mutationFn: (body: OrgSettingsInput) => orgSettingsApi.update(body),
    onSuccess: (saved) => {
      queryClient.setQueryData(['org', 'settings'], saved);
      // Every country-expense figure is derived from these, so the reports
      // showing them are stale the moment they change.
      queryClient.invalidateQueries({ queryKey: ['reports', 'country-expenses'] });
      toast({ title: t('settings.rates.saved') });
    },
    onError: (error: unknown) => {
      toast({
        title: t('settings.rates.saveFailed'),
        description: error instanceof ApiError ? error.detail : undefined,
        variant: 'destructive',
      });
    },
  });

  function submit() {
    const parse = (value: string): number | null => {
      const trimmed = value.trim();
      if (trimmed === '') return null;
      const n = Number(trimmed);
      return Number.isFinite(n) && n > 0 ? n : null;
    };
    save.mutate({
      usd_to_kzt: parse(draft.usd_to_kzt),
      usd_to_rub: parse(draft.usd_to_rub),
      usd_to_uzs: parse(draft.usd_to_uzs),
    });
  }

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Coins className="h-5 w-5" /> {t('settings.rates.title')}
        </CardTitle>
        <CardDescription>{t('settings.rates.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              {FIELDS.map(({ key, currency, labelKey }) => (
                <div key={key} className="space-y-1.5">
                  <Label htmlFor={key}>{t(labelKey)}</Label>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">1 USD =</span>
                    <Input
                      id={key}
                      inputMode="decimal"
                      placeholder="—"
                      value={draft[key]}
                      disabled={!canEdit}
                      onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                    />
                    <span className="text-sm text-muted-foreground">{currency}</span>
                  </div>
                </div>
              ))}
            </div>

            <p className="text-xs text-muted-foreground">{t('settings.rates.hint')}</p>

            {canEdit && (
              <Button onClick={submit} disabled={save.isPending}>
                {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t('common.save')}
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
