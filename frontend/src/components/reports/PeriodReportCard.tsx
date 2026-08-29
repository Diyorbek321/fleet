import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Download, FileSpreadsheet, Loader2, TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ApiError } from '@/lib/api';
import { PERIOD_CHOICES, reportsApi, type PeriodChoice } from '@/lib/reports';
import { formatAmount, formatKm } from '@/lib/format';
import { toast } from '@/hooks/use-toast';

/**
 * The closing report for a calendar month or week.
 *
 * Separate from the rolling-window figures above it on the page, and
 * deliberately so: "last 30 days" answers how things are going, and changes
 * every time you look. This answers what August was, and returns the same
 * numbers to whoever opens it, whenever they open it. That is what makes it
 * something an owner can send to an accountant or an investor.
 */
export function PeriodReportCard() {
  const { t } = useTranslation();
  const [choice, setChoice] = useState<PeriodChoice>(PERIOD_CHOICES[0]);
  const [downloading, setDownloading] = useState(false);

  const { data: report, isLoading } = useQuery({
    queryKey: ['reports', 'period', choice.kind, choice.offset],
    queryFn: () => reportsApi.period(choice.kind, choice.offset),
  });

  async function download() {
    setDownloading(true);
    try {
      const { blob, filename } = await reportsApi.periodXlsx(choice.kind, choice.offset);
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
        title: t('reports.downloadFailed'),
        description: error instanceof ApiError ? error.detail : undefined,
        variant: 'destructive',
      });
    } finally {
      setDownloading(false);
    }
  }

  const money = (value: number) => `${formatAmount(value)} ${t('common.sum')}`;

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-4">
        <div>
          <CardTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5" /> {t('reports.periodTitle')}
          </CardTitle>
          <CardDescription>
            {report ? `${report.label} · ${report.start} – ${report.end}` : t('reports.periodHint')}
          </CardDescription>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {PERIOD_CHOICES.map((option) => (
            <Button
              key={`${option.kind}-${option.offset}`}
              size="sm"
              variant={
                option.kind === choice.kind && option.offset === choice.offset
                  ? 'default'
                  : 'outline'
              }
              onClick={() => setChoice(option)}
            >
              {t(option.labelKey)}
            </Button>
          ))}
          <Button size="sm" onClick={download} disabled={downloading || !report}>
            {downloading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            Excel
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}

        {report && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Figure label={t('reports.revenue')} value={money(report.revenue)} />
              <Figure label={t('reports.costs')} value={money(report.total_cost)} />
              <Figure
                label={t('reports.profit')}
                value={money(report.profit)}
                // Coloured because it is the one number on the page that can be
                // negative, and a loss should not read like a total.
                tone={report.profit >= 0 ? 'good' : 'bad'}
              />
              <Figure label={t('reports.margin')} value={`${report.margin_pct}%`} />
              <Figure
                label={t('reports.tripsDelivered')}
                value={String(report.trips_delivered)}
              />
              <Figure
                label={t('reports.tripsInProgress')}
                value={String(report.trips_in_progress)}
              />
              <Figure
                label={t('reports.distance')}
                value={`${formatKm(report.distance_km)} ${t('reports.km')}`}
              />
              <Figure
                label={t('reports.consumption')}
                // Withheld rather than shown with an asterisk: a number on a
                // dashboard gets quoted, and the caveat does not travel with it.
                value={
                  report.consumption_reliable && report.l_per_100km !== null
                    ? `${report.l_per_100km} L/100km`
                    : '—'
                }
              />
            </div>

            {!report.consumption_reliable && (
              <Note>{t('reports.consumptionUnreliable')}</Note>
            )}
            {report.distance_partial && <Note>{t('reports.distancePartial')}</Note>}

            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('reports.truck')}</TableHead>
                    <TableHead className="text-right">{t('reports.trips')}</TableHead>
                    <TableHead className="text-right">{t('reports.revenue')}</TableHead>
                    <TableHead className="text-right">{t('reports.costs')}</TableHead>
                    <TableHead className="text-right">{t('reports.profit')}</TableHead>
                    <TableHead className="text-right">{t('reports.km')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.trucks.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                        {t('reports.periodEmpty')}
                      </TableCell>
                    </TableRow>
                  )}
                  {report.trucks.map((line) => (
                    <TableRow key={line.truck_id}>
                      <TableCell>
                        <div className="font-medium">{line.name}</div>
                        <div className="text-xs text-muted-foreground">{line.plate_number}</div>
                      </TableCell>
                      <TableCell className="text-right">{line.trips}</TableCell>
                      <TableCell className="text-right">{formatAmount(line.revenue)}</TableCell>
                      <TableCell className="text-right">
                        {formatAmount(line.total_cost)}
                      </TableCell>
                      <TableCell
                        className={`text-right font-medium ${
                          line.profit >= 0 ? 'text-emerald-600' : 'text-destructive'
                        }`}
                      >
                        {formatAmount(line.profit)}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatKm(line.distance_km)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'good' | 'bad';
}) {
  const colour =
    tone === 'good' ? 'text-emerald-600' : tone === 'bad' ? 'text-destructive' : '';
  return (
    <div className="rounded-lg border border-border/50 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${colour}`}>{value}</div>
    </div>
  );
}

function Note({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-400">
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{children}</span>
    </div>
  );
}
