import React from 'react';
import { Truck, TrendingUp, Square, WifiOff, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useTrucks } from '@/contexts/TruckContext';
import { cn } from '@/lib/utils';

interface StatCardProps {
  title: string;
  value: number;
  icon: React.ElementType;
  trend?: { value: number; positive: boolean };
  color: 'primary' | 'moving' | 'stopped' | 'offline';
}

function StatCard({ title, value, icon: Icon, trend, color }: StatCardProps) {
  const colorClasses = {
    primary: 'bg-primary/10 text-primary border-primary/20',
    moving: 'bg-status-moving/10 text-status-moving border-status-moving/20',
    stopped: 'bg-status-stopped/10 text-status-stopped border-status-stopped/20',
    offline: 'bg-status-offline/10 text-status-offline border-status-offline/20',
  };

  const iconBgClasses = {
    primary: 'bg-primary/20',
    moving: 'bg-status-moving/20',
    stopped: 'bg-status-stopped/20',
    offline: 'bg-status-offline/20',
  };

  return (
    <Card className="card-hover border-border/50 bg-card">
      <CardContent className="p-6">
        <div className="flex items-start justify-between">
          <div className="space-y-2">
            <p className="text-sm font-medium text-muted-foreground">{title}</p>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold tracking-tight">{value}</span>
              {trend && (
                <span
                  className={cn(
                    'flex items-center text-xs font-medium',
                    trend.positive ? 'text-status-moving' : 'text-destructive'
                  )}
                >
                  {trend.positive ? (
                    <ArrowUpRight className="h-3 w-3" />
                  ) : (
                    <ArrowDownRight className="h-3 w-3" />
                  )}
                  {trend.value}%
                </span>
              )}
            </div>
          </div>
          <div className={cn('rounded-xl p-3', iconBgClasses[color])}>
            <Icon className={cn('h-6 w-6', colorClasses[color].split(' ')[1])} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {[1, 2, 3, 4].map((i) => (
        <Card key={i} className="border-border/50 bg-card">
          <CardContent className="p-6">
            <div className="space-y-3">
              <div className="skeleton h-4 w-24" />
              <div className="skeleton h-8 w-16" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function StatsCards() {
  const { stats, isLoading } = useTrucks();

  if (isLoading) {
    return <LoadingSkeleton />;
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 animate-fade-in">
      <StatCard
        title="Total Trucks"
        value={stats.totalTrucks}
        icon={Truck}
        color="primary"
        trend={{ value: 12, positive: true }}
      />
      <StatCard
        title="Moving"
        value={stats.movingTrucks}
        icon={TrendingUp}
        color="moving"
      />
      <StatCard
        title="Stopped"
        value={stats.stoppedTrucks}
        icon={Square}
        color="stopped"
      />
      <StatCard
        title="Offline"
        value={stats.offlineTrucks}
        icon={WifiOff}
        color="offline"
      />
    </div>
  );
}
