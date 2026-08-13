import { useTranslation } from 'react-i18next';
import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const data = [
  { time: '00:00', moving: 4, stopped: 2, offline: 1 },
  { time: '04:00', moving: 3, stopped: 3, offline: 1 },
  { time: '08:00', moving: 6, stopped: 1, offline: 0 },
  { time: '12:00', moving: 5, stopped: 2, offline: 0 },
  { time: '16:00', moving: 7, stopped: 0, offline: 0 },
  { time: '20:00', moving: 4, stopped: 2, offline: 1 },
  { time: '24:00', moving: 3, stopped: 3, offline: 1 },
];

export function FleetOverviewChart() {
  const { t } = useTranslation();
  return (
    <Card className="border-border/50 bg-card">
      <CardHeader>
        <CardTitle className="text-lg">{t('dashboard.activity')}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="movingGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--status-moving))" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="hsl(var(--status-moving))" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="stoppedGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--status-stopped))" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="hsl(var(--status-stopped))" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="offlineGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--status-offline))" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="hsl(var(--status-offline))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis 
                dataKey="time" 
                stroke="hsl(var(--muted-foreground))" 
                fontSize={12}
                tickLine={false}
                axisLine={false}
              />
              <YAxis 
                stroke="hsl(var(--muted-foreground))" 
                fontSize={12}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '8px',
                  color: 'hsl(var(--foreground))',
                }}
              />
              <Area
                type="monotone"
                dataKey="moving"
                stackId="1"
                stroke="hsl(var(--status-moving))"
                fill="url(#movingGradient)"
                name={t('dashboard.stats.moving')}
              />
              <Area
                type="monotone"
                dataKey="stopped"
                stackId="1"
                stroke="hsl(var(--status-stopped))"
                fill="url(#stoppedGradient)"
                name={t('dashboard.stats.stopped')}
              />
              <Area
                type="monotone"
                dataKey="offline"
                stackId="1"
                stroke="hsl(var(--status-offline))"
                fill="url(#offlineGradient)"
                name={t('dashboard.stats.offline')}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Legend */}
        <div className="flex items-center justify-center gap-6 mt-4">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-status-moving" />
            <span className="text-sm text-muted-foreground">{t('dashboard.stats.moving')}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-status-stopped" />
            <span className="text-sm text-muted-foreground">{t('dashboard.stats.stopped')}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-status-offline" />
            <span className="text-sm text-muted-foreground">{t('dashboard.stats.offline')}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
