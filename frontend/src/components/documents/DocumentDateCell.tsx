import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { daysLeft, insuranceState, type InsuranceState } from '@/lib/insurance';
import { cn } from '@/lib/utils';

const STATE_CLASSES: Record<InsuranceState, string> = {
  expired: 'bg-destructive/15 text-destructive border-destructive/30',
  urgent: 'bg-status-stopped/20 text-status-stopped border-status-stopped/30',
  soon: 'bg-yellow-500/15 text-yellow-600 dark:text-yellow-400 border-yellow-500/30',
  ok: 'bg-status-moving/15 text-status-moving border-status-moving/30',
  missing: 'bg-muted text-muted-foreground border-border',
};

interface DocumentDateCellProps {
  /** The saved expiry, ISO date, or null/undefined when none is entered. */
  value: string | null | undefined;
  today: string;
  ariaLabel: string;
  /** Called with the new date, or null when it was cleared. */
  onCommit: (value: string | null) => void;
}

/** One document's expiry: a date input plus how long is left on it. */
export function DocumentDateCell({ value, today, ariaLabel, onCommit }: DocumentDateCellProps) {
  const { t } = useTranslation();
  const saved = value ?? '';
  // Held locally and saved on blur: typing a date into the segments fires a
  // change per complete date, and a save per keystroke is a toast per keystroke.
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);

  const state = insuranceState(draft, today);
  const days = draft ? daysLeft(draft, today) : 0;
  const label =
    state === 'missing'
      ? t('insurance.state.missing')
      : state === 'expired'
        ? t('insurance.state.expired', { count: Math.abs(days) })
        : t('insurance.state.left', { count: days });

  const commit = () => {
    if (draft !== saved) onCommit(draft || null);
  };

  return (
    <div className="flex min-w-[9.5rem] flex-col gap-1">
      <Input
        type="date"
        value={draft}
        className="h-8 bg-secondary/50 border-0 px-2 text-sm"
        aria-label={ariaLabel}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
        }}
      />
      <Badge variant="outline" className={cn('w-fit text-[11px] font-normal', STATE_CLASSES[state])}>
        {label}
      </Badge>
    </div>
  );
}
