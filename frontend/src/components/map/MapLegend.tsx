import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';

const LEGEND_ITEMS = [
  { status: 'moving', color: 'bg-status-moving' },
  { status: 'stopped', color: 'bg-status-stopped' },
  { status: 'offline', color: 'bg-status-offline' },
] as const;

interface MapLegendProps {
  /** Whether the live position stream is connected. */
  live: boolean;
}

export function MapLegend({ live }: MapLegendProps) {
  const { t } = useTranslation();

  return (
    <Card className="absolute bottom-4 left-4 z-10 border-border/50 bg-card/90 backdrop-blur-sm shadow-card">
      <CardContent className="p-3">
        <div className="flex gap-4">
          {LEGEND_ITEMS.map((item) => (
            <div key={item.status} className="flex items-center gap-2">
              <div className={`h-3 w-3 rounded-full ${item.color}`} />
              <span className="text-xs text-muted-foreground">{t(`trucks.status.${item.status}`)}</span>
            </div>
          ))}
          {/* Frozen markers look exactly like parked trucks; say which it is. */}
          <div className="flex items-center gap-2 border-l border-border/50 pl-4">
            <span className={`h-2 w-2 rounded-full ${live ? 'bg-status-moving' : 'animate-pulse bg-destructive'}`} />
            <span className={`text-xs ${live ? 'text-muted-foreground' : 'font-medium text-destructive'}`}>
              {live ? t('map.live') : t('map.reconnecting')}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
