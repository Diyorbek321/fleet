import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Fuel, OctagonAlert, Timer, TrendingDown } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
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
import { analyticsApi } from '@/lib/analytics';

function fmtUZS(n: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(n));
}

export default function LeakagePage() {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);

  const { data: summary } = useQuery({
    queryKey: ['leakage-summary', days],
    queryFn: () => analyticsApi.leakageSummary(days),
    refetchInterval: 60_000,
  });
  const { data: fuel = [] } = useQuery({
    queryKey: ['fuel-anomalies', days],
    queryFn: () => analyticsApi.fuelAnomalies(days),
  });
  const { data: stops = [] } = useQuery({
    queryKey: ['unauthorized-stops', days],
    queryFn: () => analyticsApi.unauthorizedStops(days),
  });

  const cards = [
    {
      icon: TrendingDown,
      label: t('leakage.fuelWaste'),
      value: `${fmtUZS(summary?.estimatedFuelWasteCost ?? 0)} UZS`,
      hint: t('leakage.fuelWasteHint', { count: summary?.flaggedTrucks ?? 0 }),
      accent: 'text-red-500',
    },
    {
      icon: OctagonAlert,
      label: t('leakage.unauthorizedStops'),
      value: String(summary?.unauthorizedStopCount ?? 0),
      hint: t('leakage.unauthorizedStopsHint'),
      accent: 'text-amber-500',
    },
    {
      icon: Timer,
      label: t('leakage.idleHours'),
      value: `${summary?.totalIdleHours ?? 0} h`,
      hint: t('leakage.idleHoursHint'),
      accent: 'text-orange-500',
    },
    {
      icon: Fuel,
      label: t('leakage.baseline'),
      value: `${summary?.fuelBaselineLPer100km ?? 0} L/100km`,
      hint: t('leakage.activeTrips', { count: summary?.activeTrips ?? 0 }),
      accent: 'text-sky-500',
    },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('leakage.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('leakage.subtitle')}</p>
        </div>
        <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
          <SelectTrigger className="w-[160px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="7">{t('leakage.last7')}</SelectItem>
            <SelectItem value="30">{t('leakage.last30')}</SelectItem>
            <SelectItem value="90">{t('leakage.last90')}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((c) => (
          <Card key={c.label}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{c.label}</CardTitle>
              <c.icon className={`h-5 w-5 ${c.accent}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{c.value}</div>
              <p className="text-xs text-muted-foreground mt-1">{c.hint}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Fuel anomalies */}
      <Card>
        <CardHeader>
          <CardTitle>{t('leakage.fuelEfficiency')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('leakage.truck')}</TableHead>
                <TableHead className="text-right">{t('leakage.distance')}</TableHead>
                <TableHead className="text-right">{t('leakage.liters')}</TableHead>
                <TableHead className="text-right">L/100km</TableHead>
                <TableHead className="text-right">{t('leakage.wasteCost')}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {fuel.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-6">
                    {t('leakage.noData')}
                  </TableCell>
                </TableRow>
              )}
              {fuel.map((r) => (
                <TableRow key={r.truckId} className={r.flagged ? 'bg-red-500/5' : undefined}>
                  <TableCell className="font-medium">
                    {r.truckName}
                    <span className="text-muted-foreground font-mono text-xs ml-2">{r.plateNumber}</span>
                  </TableCell>
                  <TableCell className="text-right">{r.distanceKm} km</TableCell>
                  <TableCell className="text-right">{r.liters} L</TableCell>
                  <TableCell className="text-right font-medium">
                    {r.lPer100km}
                    <span className="text-muted-foreground text-xs"> / {r.baselineLPer100km}</span>
                  </TableCell>
                  <TableCell className="text-right">
                    {r.estimatedWasteCost > 0 ? `${fmtUZS(r.estimatedWasteCost)} UZS` : '—'}
                  </TableCell>
                  <TableCell>
                    {r.flagged && <Badge variant="destructive">{t('leakage.flagged')}</Badge>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Unauthorized stops */}
      <Card>
        <CardHeader>
          <CardTitle>{t('leakage.unauthorizedStops')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('leakage.truck')}</TableHead>
                <TableHead>{t('leakage.location')}</TableHead>
                <TableHead>{t('leakage.start')}</TableHead>
                <TableHead className="text-right">{t('leakage.duration')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stops.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground py-6">
                    {t('leakage.noStops')}
                  </TableCell>
                </TableRow>
              )}
              {stops.map((s, i) => (
                <TableRow key={`${s.truckId}-${i}`}>
                  <TableCell className="font-medium">
                    {s.truckName}
                    <span className="text-muted-foreground font-mono text-xs ml-2">{s.plateNumber}</span>
                  </TableCell>
                  <TableCell>
                    <a
                      className="text-sky-500 hover:underline"
                      href={`https://maps.google.com/?q=${s.latitude},${s.longitude}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {s.latitude.toFixed(4)}, {s.longitude.toFixed(4)}
                    </a>
                  </TableCell>
                  <TableCell className="text-sm">{new Date(s.startedAt).toLocaleString()}</TableCell>
                  <TableCell className="text-right">{Math.round(s.durationMinutes)} min</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
