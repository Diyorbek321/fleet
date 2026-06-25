import React from 'react';
import { X, MapPin, Gauge, Clock, User, Truck as TruckIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Truck } from '@/types';
import { cn } from '@/lib/utils';
import { formatDistanceToNow } from 'date-fns';

interface TruckPopupProps {
  truck: Truck;
  onClose: () => void;
}

export function TruckPopup({ truck, onClose }: TruckPopupProps) {
  const statusBadgeClasses = {
    moving: 'bg-status-moving/20 text-status-moving border-status-moving/30',
    stopped: 'bg-status-stopped/20 text-status-stopped border-status-stopped/30',
    offline: 'bg-status-offline/20 text-status-offline border-status-offline/30',
  };

  return (
    <Card className="absolute top-4 right-4 z-10 w-80 border-border/50 bg-card/95 backdrop-blur-sm shadow-elevated animate-slide-in-right">
      <CardContent className="p-4">
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                'flex h-10 w-10 items-center justify-center rounded-lg',
                truck.status === 'moving' && 'bg-status-moving/20',
                truck.status === 'stopped' && 'bg-status-stopped/20',
                truck.status === 'offline' && 'bg-status-offline/20'
              )}
            >
              <TruckIcon
                className={cn(
                  'h-5 w-5',
                  truck.status === 'moving' && 'text-status-moving',
                  truck.status === 'stopped' && 'text-status-stopped',
                  truck.status === 'offline' && 'text-status-offline'
                )}
              />
            </div>
            <div>
              <h3 className="font-semibold">{truck.plateNumber}</h3>
              <p className="text-xs text-muted-foreground">{truck.id}</p>
            </div>
          </div>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Status */}
        <div className="flex items-center gap-2 mb-4">
          <Badge
            variant="outline"
            className={cn('capitalize', statusBadgeClasses[truck.status])}
          >
            {truck.status === 'moving' && (
              <span className="relative flex h-2 w-2 mr-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-current"></span>
              </span>
            )}
            {truck.status}
          </Badge>
        </div>

        {/* Details */}
        <div className="space-y-3">
          <div className="flex items-center gap-3 text-sm">
            <Gauge className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">Speed:</span>
            <span className="font-mono font-medium">{truck.speed} km/h</span>
          </div>

          <div className="flex items-center gap-3 text-sm">
            <MapPin className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">Location:</span>
            <span className="font-mono text-xs">
              {truck.latitude.toFixed(5)}, {truck.longitude.toFixed(5)}
            </span>
          </div>

          <div className="flex items-center gap-3 text-sm">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">Updated:</span>
            <span>{formatDistanceToNow(truck.lastUpdate, { addSuffix: true })}</span>
          </div>

          {truck.driverName && (
            <div className="flex items-center gap-3 text-sm">
              <User className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">Driver:</span>
              <span>{truck.driverName}</span>
            </div>
          )}
        </div>

        {/* Truck info */}
        <div className="mt-4 pt-4 border-t border-border/50">
          <div className="text-sm">
            <span className="text-muted-foreground">Model: </span>
            <span>{truck.name}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
