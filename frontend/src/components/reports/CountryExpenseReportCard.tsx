import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Download, Globe2, Loader2, TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ApiError } from '@/lib/api';
import { RANGE_CHOICES, countryExpensesApi } from '@/lib/countryExpenses';
import { trucksApi } from '@/lib/trucks';
import { toast } from '@/hooks/use-toast';
import { CountryBreakdownTables } from '@/components/reports/CountryBreakdownTables';
import { CountryTotalsCards } from '@/components/reports/CountryTotalsCards';
import { CountryTripsTable } from '@/components/reports/CountryTripsTable';
import { countryLabel, usdMoney } from '@/components/reports/countryExpenseLabels';

/**
 * Where a truck's money went, country by country, run by run.
 *
 * The report answers one question that no other screen does: a lorry left,
 * crossed two borders and came back — how much did it burn in Kazakhstan
 * versus Russia versus at home, and on what. The data comes from the "yo'l
 * varaqasi" the driver fills in on the phone; this is the reading end of it.
 *
 * Two tabs because there are two readings. "Summary" is the whole range added
 * up — the shape of your spending. "Trips" is one row per round trip, which is
 * what you open when one number in the summary looks wrong.
 *
 * Pass `truckId` to pin it to one lorry (the truck page does); leave it out and
 * the user picks, defaulting to the whole fleet.
 */
export function CountryExpenseReportCard({ truckId }: { truckId?: string }) {
  const { t, i18n } = useTranslation();
  const [rangeKey, setRangeKey] = useState(RANGE_CHOICES[0].key);
  const [selectedTruck, setSelectedTruck] = useState<string>('all');
  const [downloading, setDownloading] = useState(false);

  // Resolved from today at render time, not stored: a tab left open overnight
  // must not keep reporting yesterday's idea of "this month".
  const range = useMemo(() => {
    const choice = RANGE_CHOICES.find((c) => c.key === rangeKey) ?? RANGE_CHOICES[0];
    return choice.resolve(new Date());
  }, [rangeKey]);

  const effectiveTruck = truckId ?? (selectedTruck === 'all' ? undefined : selectedTruck);
  const query = { ...range, truckId: effectiveTruck };

  const { data: report, isLoading } = useQuery({
    queryKey: ['reports', 'country-expenses', range.from, range.to, effectiveTruck ?? 'all'],
    queryFn: () => countryExpensesApi.get(query),
  });

  // Only needed for the picker, so the truck page — which already knows which
  // lorry it is — never fetches the list.
  const { data: trucks } = useQuery({
    queryKey: ['trucks'],
    queryFn: trucksApi.list,
    enabled: !truckId,
  });

  async function download() {
    setDownloading(true);
    try {
      const { blob, filename } = await countryExpensesApi.xlsx(query);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (error: unknown) {
      toast({
        title: t('countryExpenses.downloadFailed'),
        description: error instanceof ApiError ? error.detail : undefined,
        variant: 'destructive',
      });
    } finally {
      setDownloading(false);
    }
  }

  const missing = report?.countries_missing_rate ?? [];
  const dateFmt = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' });
  const rangeLabel = report
    ? `${dateFmt.format(new Date(report.start))} – ${dateFmt.format(new Date(report.end))}`
    : '';

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Globe2 className="h-5 w-5" /> {t('countryExpenses.title')}
          </CardTitle>
          <CardDescription>{t('countryExpenses.subtitle')}</CardDescription>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Select value={rangeKey} onValueChange={setRangeKey}>
            <SelectTrigger className="w-[170px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGE_CHOICES.map((choice) => (
                <SelectItem key={choice.key} value={choice.key}>
                  {t(choice.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {!truckId && (
            <Select value={selectedTruck} onValueChange={setSelectedTruck}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder={t('countryExpenses.allTrucks')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('countryExpenses.allTrucks')}</SelectItem>
                {(trucks ?? []).map((truck) => (
                  <SelectItem key={truck.id} value={truck.id}>
                    {truck.plateNumber} · {truck.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          <Button
            variant="outline"
            onClick={download}
            disabled={downloading || !report || report.trips.length === 0}
          >
            {downloading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            {t('countryExpenses.download')}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : !report ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {t('countryExpenses.empty')}
          </p>
        ) : (
          <>
            {missing.length > 0 && (
              // Not a toast: this is a standing condition, not an event. It
              // stays on the screen until someone sets a rate, because until
              // then the USD column is telling only part of the story.
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                <TriangleAlert className="h-4 w-4 shrink-0 text-amber-500" />
                <span>
                  {t('countryExpenses.missingRate', {
                    countries: missing.map((c) => countryLabel(t, c)).join(', '),
                  })}
                </span>
                <Link to="/settings" className="font-medium text-primary hover:underline">
                  {t('countryExpenses.setRates')}
                </Link>
              </div>
            )}

            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-sm text-muted-foreground">
                {t('countryExpenses.grandTotal')}
              </span>
              <span className="text-2xl font-bold tabular-nums">{usdMoney(report.total_usd)}</span>
              <span className="text-sm text-muted-foreground">
                {t('countryExpenses.tripCount', { count: report.trips.length })} · {rangeLabel}
              </span>
            </div>

            <Tabs defaultValue="summary">
              <TabsList>
                <TabsTrigger value="summary">{t('countryExpenses.tabSummary')}</TabsTrigger>
                <TabsTrigger value="trips">{t('countryExpenses.tabTrips')}</TabsTrigger>
              </TabsList>

              <TabsContent value="summary" className="space-y-6 pt-4">
                <CountryTotalsCards countries={report.countries} totalUsd={report.total_usd} />
                <CountryBreakdownTables countries={report.countries} cards={report.cards} />
              </TabsContent>

              <TabsContent value="trips" className="pt-4">
                <CountryTripsTable trips={report.trips} />
              </TabsContent>
            </Tabs>
          </>
        )}
      </CardContent>
    </Card>
  );
}
