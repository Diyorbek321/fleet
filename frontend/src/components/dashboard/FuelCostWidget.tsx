import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Fuel, DollarSign, Gauge, TrendingUp } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { maintenanceApi, type FuelSummary } from '@/lib/maintenance';

function formatUSD(n: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
}

function formatNum(n: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(n));
}

export function FuelCostWidget() {
  const { data, isLoading, isError } = useQuery<FuelSummary>({
    queryKey: ['fuel-summary', 30],
    queryFn: () => maintenanceApi.fuelSummary(30),
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return (
      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle>Fuel & Efficiency (30 days)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="skeleton h-32 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle>Fuel & Efficiency (30 days)</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No fuel data available yet.</p>
        </CardContent>
      </Card>
    );
  }

  const topTrucks = data.trucks.slice(0, 3);
  const bottomTruck = data.trucks[data.trucks.length - 1];

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Fuel & Efficiency</span>
          <span className="text-xs font-normal text-muted-foreground">last {data.days} days</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat
            icon={DollarSign}
            label="Total Fuel Cost"
            value={formatUSD(data.total_cost)}
            tone="primary"
          />
          <Stat
            icon={Fuel}
            label="Gallons Burned"
            value={formatNum(data.total_gallons)}
            tone="moving"
          />
          <Stat
            icon={Gauge}
            label="Fleet MPG"
            value={data.fleet_mpg > 0 ? data.fleet_mpg.toFixed(2) : '—'}
            tone="stopped"
          />
          <Stat
            icon={TrendingUp}
            label="Avg $/gal"
            value={`$${data.avg_price_per_gallon.toFixed(2)}`}
            tone="primary"
          />
        </div>

        {topTrucks.length > 0 && (
          <div>
            <h4 className="mb-2 text-sm font-semibold text-muted-foreground">Top Performers (MPG)</h4>
            <div className="space-y-2">
              {topTrucks.map((t) => (
                <div key={t.truck_id} className="flex items-center justify-between rounded-lg border border-border/40 bg-background/50 px-3 py-2">
                  <div>
                    <p className="text-sm font-medium">{t.truck_name}</p>
                    <p className="text-xs text-muted-foreground">{t.plate_number} · {formatNum(t.miles)} mi</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-bold">{t.mpg.toFixed(2)} mpg</p>
                    <p className="text-xs text-muted-foreground">{formatUSD(t.cost)}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {bottomTruck && data.trucks.length > 3 && bottomTruck.mpg > 0 && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2">
            <p className="text-xs font-semibold text-destructive">⚠ Lowest MPG: {bottomTruck.truck_name}</p>
            <p className="text-xs text-muted-foreground">
              {bottomTruck.mpg.toFixed(2)} mpg · {formatUSD(bottomTruck.cost)} this period · check engine/tire health
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
