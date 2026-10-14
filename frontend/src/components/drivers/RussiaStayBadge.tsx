import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { stayLevel, type StaySummary } from '@/lib/russiaStays';

/** "day 47 · 43 left" for a driver now in Russia; nothing otherwise. */
export function RussiaStayBadge({ summary }: { summary: StaySummary | undefined }) {
  const { t } = useTranslation();
  if (!summary?.in_russia) return null;
  const level = stayLevel(summary);
  const left = summary.days_to_leave ?? 0;
  return (
    <Badge
      variant={level === 'urgent' || level === 'over' ? 'destructive' : 'outline'}
      className={level === 'soon' ? 'border-status-stopped/50 text-status-stopped' : undefined}
    >
      {level === 'over'
        ? t('russiaStay.overstay', { n: summary.overstay_days || -left })
        : t('russiaStay.columnDays', { day: summary.day_of_stay, n: left })}
    </Badge>
  );
}
