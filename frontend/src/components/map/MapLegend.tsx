import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';

const LEGEND_ITEMS = [
  { status: 'moving', color: 'bg-status-moving' },
  { status: 'stopped', color: 'bg-status-stopped' },
  { status: 'offline', color: 'bg-status-offline' },
] as const;

export function MapLegend() {
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
        </div>
      </CardContent>
    </Card>
  );
}
