import React from 'react';
import { Card, CardContent } from '@/components/ui/card';

export function MapLegend() {
  const legendItems = [
    { label: 'Moving', color: 'bg-status-moving' },
    { label: 'Stopped', color: 'bg-status-stopped' },
    { label: 'Offline', color: 'bg-status-offline' },
  ];

  return (
    <Card className="absolute bottom-4 left-4 z-10 border-border/50 bg-card/90 backdrop-blur-sm shadow-card">
      <CardContent className="p-3">
        <div className="flex gap-4">
          {legendItems.map((item) => (
            <div key={item.label} className="flex items-center gap-2">
              <div className={`h-3 w-3 rounded-full ${item.color}`} />
              <span className="text-xs text-muted-foreground">{item.label}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
