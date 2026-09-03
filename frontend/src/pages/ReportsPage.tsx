import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Truck, Users, Gauge, Wrench, Fuel, Download, Loader2, Sparkles, Wallet } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { CountryExpenseReportCard } from '@/components/reports/CountryExpenseReportCard';
import { PeriodReportCard } from '@/components/reports/PeriodReportCard';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/hooks/use-toast';
import { ApiError } from '@/lib/api';
import {
  reportsApi,
  type ReportLanguage,
  type ReportType,
} from '@/lib/reports';

const REPORT_TYPES: ReportType[] = ['fuel', 'maintenance', 'trucks', 'drivers', 'full'];
const REPORT_LANGUAGES: ReportLanguage[] = ['en', 'ru', 'uz'];

const WINDOW_OPTIONS = [7, 14, 30, 90, 180, 365] as const;

function formatNumber(value: number, fractionDigits = 0): string {
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

export default function ReportsPage() {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { toast } = useToast();
  const [days, setDays] = useState(30);
  const [reportType, setReportType] = useState<ReportType>('full');
  const [reportLanguage, setReportLanguage] = useState<ReportLanguage>(
    REPORT_LANGUAGES.find((l) => i18n.language?.startsWith(l)) ?? 'en',
  );
  const [isGenerating, setIsGenerating] = useState(false);

  const isAdmin = user?.role === 'admin';

  const handleGenerate = async (): Promise<void> => {
    setIsGenerating(true);
    try {
      const { blob, filename } = await reportsApi.generate(reportType, reportLanguage, days);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast({ title: t('reports.generateSuccess') });
    } catch (error: unknown) {
      const detail = error instanceof ApiError ? error.detail : t('reports.generateFailed');
      toast({
        title: t('reports.generateFailed'),
        description: detail,
        variant: 'destructive',
      });
    } finally {
      setIsGenerating(false);
    }
  };

  const summaryQuery = useQuery({
    queryKey: ['reports', 'fleet-summary', days],
    queryFn: () => reportsApi.fleetSummary(days),
    refetchInterval: 60_000,
  });

  const distancesQuery = useQuery({
    queryKey: ['reports', 'truck-distances', days],
    queryFn: () => reportsApi.truckDistances(days),
    refetchInterval: 60_000,
  });

  const expensesQuery = useQuery({
    queryKey: ['reports', 'driver-expenses', days],
    queryFn: () => reportsApi.driverExpenses(days),
    refetchInterval: 60_000,
  });

  const summary = summaryQuery.data;
  const distances = distancesQuery.data ?? [];
  const expenseRanks = expensesQuery.data ?? [];
  const maxExpense = expenseRanks.reduce((m, r) => Math.max(m, r.total), 0);

  const dateFmt = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' });

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('reports.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('reports.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-muted-foreground">{t('reports.windowDays')}</label>
          <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOW_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {t('reports.windowLast', { days: n })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {summary && (
        <p className="text-xs text-muted-foreground">
          {dateFmt.format(summary.windowStart)} → {dateFmt.format(summary.windowEnd)}
        </p>
      )}

      {/* The closing document, above the rolling-window figures: it is what
          someone comes to this page to produce. */}
      <PeriodReportCard />

      {/* Directly under it: the same money, cut by where it was spent rather
          than by when. A cross-border fleet asks both questions. */}
      <CountryExpenseReportCard />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <SummaryCard
          icon={<Truck className="h-5 w-5" />}
          label={t('reports.totalTrucks')}
          value={summary ? formatNumber(summary.totalTrucks) : '—'}
        />
        <SummaryCard
          icon={<Users className="h-5 w-5" />}
          label={t('reports.activeDrivers')}
          value={summary ? formatNumber(summary.activeDrivers) : '—'}
        />
        <SummaryCard
          icon={<Gauge className="h-5 w-5" />}
          label={t('reports.distance')}
          value={summary ? `${formatNumber(summary.distanceKm, 1)} ${t('reports.km')}` : '—'}
        />
        <SummaryCard
          icon={<Fuel className="h-5 w-5" />}
          label={t('reports.fuelCost')}
          value={
            summary
              ? `${formatNumber(summary.totalFuelCost)} ${t('common.currency')}`
              : '—'
          }
          secondary={
            summary
              ? `${formatNumber(summary.totalFuelLiters, 0)} ${t('common.liters')}`
              : undefined
          }
        />
        <SummaryCard
          icon={<Wrench className="h-5 w-5" />}
          label={t('reports.maintenanceCost')}
          value={
            summary
              ? `${formatNumber(summary.totalMaintenanceCost)} ${t('common.currency')}`
              : '—'
          }
        />
      </div>

      {isAdmin && (
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              {t('reports.aiTitle')}
            </CardTitle>
            <p className="text-sm text-muted-foreground">{t('reports.aiSubtitle')}</p>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-muted-foreground">{t('reports.reportType')}</label>
                <Select value={reportType} onValueChange={(v) => setReportType(v as ReportType)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {REPORT_TYPES.map((rt) => (
                      <SelectItem key={rt} value={rt}>
                        {t(`reports.type.${rt}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-muted-foreground">{t('reports.language')}</label>
                <Select
                  value={reportLanguage}
                  onValueChange={(v) => setReportLanguage(v as ReportLanguage)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {REPORT_LANGUAGES.map((l) => (
                      <SelectItem key={l} value={l}>
                        {t(`reports.lang.${l}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-end">
                <Button
                  onClick={handleGenerate}
                  disabled={isGenerating}
                  className="w-full"
                >
                  {isGenerating ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4 mr-2" />
                  )}
                  {t('reports.download')}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle className="text-lg">{t('reports.byTruck')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('reports.truck')}</TableHead>
                <TableHead>{t('reports.plate')}</TableHead>
                <TableHead className="text-right">{t('reports.distance')}</TableHead>
                <TableHead className="text-right">{t('reports.points')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {distances.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground py-6">
                    {t('reports.noData')}
                  </TableCell>
                </TableRow>
              )}
              {distances.map((d) => (
                <TableRow key={d.truckId}>
                  <TableCell className="font-medium">{d.truckName}</TableCell>
                  <TableCell className="font-mono text-xs">{d.plateNumber}</TableCell>
                  <TableCell className="text-right font-mono">
                    {formatNumber(d.distanceKm, 1)} {t('reports.km')}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {formatNumber(d.pointCount)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Wallet className="h-5 w-5 text-primary" />
            {t('reports.expensesTitle')}
          </CardTitle>
          <p className="text-sm text-muted-foreground">{t('reports.expensesSubtitle')}</p>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('reports.driver')}</TableHead>
                <TableHead>{t('reports.share')}</TableHead>
                <TableHead className="text-right">{t('reports.entries')}</TableHead>
                <TableHead className="text-right">{t('reports.total')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {expenseRanks.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground py-6">
                    {t('reports.noData')}
                  </TableCell>
                </TableRow>
              )}
              {expenseRanks.map((r, i) => (
                <TableRow key={r.driverId}>
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2">
                      <span>{r.driverName}</span>
                      {i === 0 && expenseRanks.length > 1 && (
                        <span className="rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] font-semibold text-destructive">
                          {t('reports.highest')}
                        </span>
                      )}
                      {i === expenseRanks.length - 1 && expenseRanks.length > 1 && (
                        <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-600">
                          {t('reports.lowest')}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="w-[40%]">
                    <div className="h-2 w-full rounded-full bg-muted">
                      <div
                        className="h-2 rounded-full bg-primary"
                        style={{ width: `${maxExpense ? (r.total / maxExpense) * 100 : 0}%` }}
                      />
                    </div>
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {formatNumber(r.entryCount)}
                  </TableCell>
                  <TableCell className="text-right font-mono font-semibold">
                    {formatNumber(r.total)} {t('common.currency')}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

interface SummaryCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  secondary?: string;
}

function SummaryCard({ icon, label, value, secondary }: SummaryCardProps) {
  return (
    <Card className="border-border/50 bg-card">
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-primary/10 p-2 text-primary">{icon}</div>
          <div>
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-xl font-bold">{value}</p>
            {secondary && <p className="text-xs text-muted-foreground">{secondary}</p>}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
