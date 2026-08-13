import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Fuel, Banknote, Gauge, TrendingUp } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { maintenanceApi, type FuelSummary } from '@/lib/maintenance';
import { analyticsApi, type FuelAnomalyRow } from '@/lib/analytics';
import { formatAmount, formatKm, formatLiters } from '@/lib/format';

const WINDOW_DAYS = 30;

/**
 * Fuel spend comes from the fuel logs, but efficiency does NOT: the log-derived
 * figure divides litres by an odometer delta that only covers the span between
 * the first and last fill, which undercounts distance badly (and collapses to
 * zero for trucks with a single fill). The analytics endpoint measures distance
 * from GPS history instead, so consumption here matches the Leakage page rather
 * than contradicting it.
 */
function fleetConsumption(rows: FuelAnomalyRow[]): number | null {
  const distance = rows.reduce((sum, r) => sum + r.distanceKm, 0);
  const liters = rows.reduce((sum, r) => sum + r.liters, 0);
  if (distance <= 0 || liters <= 0) return null;
  return (liters / distance) * 100;
}

/** Only trucks that actually moved can be ranked on consumption. */
function rankable(rows: FuelAnomalyRow[]): FuelAnomalyRow[] {
  return rows.filter((r) => r.distanceKm > 0 && r.lPer100km > 0);
}

export function FuelCostWidget() {
  const { t } = useTranslation();

  const summary = useQuery<FuelSummary>({
    queryKey: ['fuel-summary', WINDOW_DAYS],
    queryFn: () => maintenanceApi.fuelSummary(WINDOW_DAYS),
    refetchInterval: 60_000,
  });

  const anomalies = useQuery<FuelAnomalyRow[]>({
    queryKey: ['fuel-anomalies', WINDOW_DAYS],
    queryFn: () => analyticsApi.fuelAnomalies(WINDOW_DAYS),
    refetchInterval: 60_000,
  });

  if (summary.isLoading || anomalies.isLoading) {
    return (
      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle>{t('dashboard.fuel.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="skeleton h-32 w-full" />
        </CardContent>
      </Card>
    );
  }

  const data = summary.data;
  if (summary.isError || !data) {
    return (
      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle>{t('dashboard.fuel.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{t('dashboard.fuel.noData')}</p>
        </CardContent>
      </Card>
    );
  }

  const rows = rankable(anomalies.data ?? []);
  const byEfficiency = [...rows].sort((a, b) => a.lPer100km - b.lPer100km);
  const topTrucks = byEfficiency.slice(0, 3);
  const worstTruck = byEfficiency[byEfficiency.length - 1];
  const consumption = fleetConsumption(rows);

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>{t('dashboard.fuel.title')}</span>
          <span className="text-xs font-normal text-muted-foreground">
            {t('dashboard.fuel.window', { days: data.days })}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat
            icon={Banknote}
            label={t('dashboard.fuel.totalCost')}
            value={`${formatAmount(data.total_cost)} ${t('common.currency')}`}
            tone="primary"
          />
          <Stat
            icon={Fuel}
            label={t('dashboard.fuel.litersBurned')}
            value={`${formatLiters(data.total_gallons)} ${t('common.liters')}`}
            tone="moving"
          />
          <Stat
            icon={Gauge}
            label={t('dashboard.fuel.fleetConsumption')}
            value={
              consumption === null
                ? '—'
                : `${consumption.toFixed(1)} ${t('common.lPer100km')}`
            }
            tone="stopped"
          />
          <Stat
            icon={TrendingUp}
            label={t('dashboard.fuel.avgLiterPrice')}
            value={`${formatAmount(data.avg_price_per_gallon)} ${t('common.currency')}`}
            tone="primary"
          />
        </div>

        {topTrucks.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold text-muted-foreground">
              {t('dashboard.fuel.topPerformers')}
            </h4>
            <div className="space-y-2">
              {topTrucks.map((truck) => (
                <div
                  key={truck.truckId}
                  className="flex items-center justify-between rounded-lg border border-border/40 bg-background/50 px-3 py-2"
                >
                  <div>
                    <p className="text-sm font-medium">{truck.truckName}</p>
                    <p className="text-xs text-muted-foreground">
                      {truck.plateNumber} · {formatKm(truck.distanceKm)} {t('common.km')}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-bold">
                      {truck.lPer100km.toFixed(1)} {t('common.lPer100km')}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatLiters(truck.liters)} {t('common.liters')}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {worstTruck && byEfficiency.length > 3 && worstTruck.flagged && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2">
            <p className="text-xs font-semibold text-destructive">
              ⚠ {t('dashboard.fuel.worstTruck', { name: worstTruck.truckName })}
            </p>
            <p className="text-xs text-muted-foreground">
              {worstTruck.lPer100km.toFixed(1)} {t('common.lPer100km')} ·{' '}
              {t('dashboard.fuel.baseline', {
                value: worstTruck.baselineLPer100km.toFixed(0),
              })}{' '}
              · {t('dashboard.fuel.worstTruckHint')}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface StatProps {
  icon: React.ElementType;
  label: string;
  value: string;
  tone: 'primary' | 'moving' | 'stopped';
}

function Stat({ icon: Icon, label, value, tone }: StatProps) {
  const bg = {
    primary: 'bg-primary/10 text-primary',
    moving: 'bg-status-moving/10 text-status-moving',
    stopped: 'bg-status-stopped/10 text-status-stopped',
  }[tone];

  return (
    <div className="rounded-lg border border-border/40 bg-background/30 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className={`rounded-md p-1.5 ${bg}`}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
      </div>
      <p className="text-xl font-bold tracking-tight">{value}</p>
    </div>
  );
}
