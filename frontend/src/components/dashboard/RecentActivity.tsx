import { useTranslation } from 'react-i18next';
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { MapPin, Clock, ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useTrucks } from '@/contexts/TruckContext';
import { cn } from '@/lib/utils';
import { formatDistanceToNow } from 'date-fns';

export function RecentActivity() {
  const { t } = useTranslation();
  const { trucks, isLoading, setSelectedTruck } = useTrucks();
  const navigate = useNavigate();

  const recentTrucks = [...trucks]
    .sort((a, b) => b.lastUpdate.getTime() - a.lastUpdate.getTime())
    .slice(0, 5);

  const statusBadgeClasses = {
    moving: 'bg-status-moving/20 text-status-moving border-status-moving/30',
    stopped: 'bg-status-stopped/20 text-status-stopped border-status-stopped/30',
    offline: 'bg-status-offline/20 text-status-offline border-status-offline/30',
  };

  const handleTruckClick = (truck: typeof trucks[0]) => {
    setSelectedTruck(truck);
    navigate('/map');
  };

  if (isLoading) {
    return (
      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle className="text-lg">{t('dashboard.recent')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-center gap-4 p-3 rounded-lg bg-secondary/30">
                <div className="skeleton h-10 w-10 rounded-full" />
                <div className="flex-1 space-y-2">
                  <div className="skeleton h-4 w-32" />
                  <div className="skeleton h-3 w-24" />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-lg">{t('dashboard.recent')}</CardTitle>
        <Button variant="ghost" size="sm" onClick={() => navigate('/trucks')}>
          {t('dashboard.viewAll')}
          <ArrowRight className="ml-1 h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {recentTrucks.map((truck) => (
            <div
              key={truck.id}
              className="flex items-center gap-4 p-3 rounded-lg bg-secondary/30 hover:bg-secondary/50 transition-colors cursor-pointer group"
              onClick={() => handleTruckClick(truck)}
            >
              <div
                className={cn(
                  'flex h-10 w-10 items-center justify-center rounded-full',
                  truck.status === 'moving' && 'bg-status-moving/20',
                  truck.status === 'stopped' && 'bg-status-stopped/20',
                  truck.status === 'offline' && 'bg-status-offline/20'
                )}
              >
                <MapPin
                  className={cn(
                    'h-5 w-5',
                    truck.status === 'moving' && 'text-status-moving',
                    truck.status === 'stopped' && 'text-status-stopped',
                    truck.status === 'offline' && 'text-status-offline'
                  )}
                />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{truck.plateNumber}</span>
                  <Badge
                    variant="outline"
                    className={cn('capitalize text-xs', statusBadgeClasses[truck.status])}
                  >
                    {truck.status}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                  <span>{truck.driverName || t('dashboard.noDriver')}</span>
                  <span>•</span>
                  <span>{truck.speed} km/h</span>
                </div>
              </div>

              <div className="text-right">
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {formatDistanceToNow(truck.lastUpdate, { addSuffix: true })}
                </div>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
