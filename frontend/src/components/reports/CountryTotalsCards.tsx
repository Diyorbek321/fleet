import { useTranslation } from 'react-i18next';
import { Fuel } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import type { CountryBlock } from '@/lib/countryExpenses';
import { formatLiters } from '@/lib/format';
import {
  countryLabel,
  hasSpending,
  nativeMoney,
  rateNote,
  usdMoney,
} from '@/components/reports/countryExpenseLabels';

/**
 * The three countries at a glance: what each one cost, in its own money.
 *
 * The big number is native — that is the figure the driver wrote down and the
 * one an owner recognises. USD sits underneath as the small print, because it
 * is derived and exists only so the three can be compared at all. The bar
 * compares the USD shares; a country with no rate simply has no bar rather
 * than a misleading one.
 */
export function CountryTotalsCards({
  countries,
  totalUsd,
}: {
  countries: CountryBlock[];
  totalUsd: number | null;
}) {
  const { t } = useTranslation();
  const spent = countries.filter(hasSpending);

  if (spent.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border/60 py-8 text-center text-sm text-muted-foreground">
        {t('countryExpenses.empty')}
      </p>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {spent.map((block) => {
        const percent =
          totalUsd && block.total_usd ? Math.round((block.total_usd / totalUsd) * 100) : null;

        return (
          <div
            key={block.country}
            className="rounded-lg border border-border/50 bg-card p-4"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium">{countryLabel(t, block.country)}</p>
              <Badge variant="outline" className="shrink-0 text-[10px] font-normal">
                {block.currency}
              </Badge>
            </div>

            <p className="mt-2 text-2xl font-bold tabular-nums">
              {nativeMoney(block.total, block.currency)}
            </p>
            <p className="text-sm text-muted-foreground tabular-nums">
              {usdMoney(block.total_usd)}
              {percent !== null && (
                <span className="ml-2 text-xs">
                  {t('countryExpenses.shareOfTotal', { percent })}
                </span>
              )}
            </p>

            {percent !== null && <Progress value={percent} className="mt-3 h-1.5" />}

            {block.fuel_liters > 0 && (
              <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Fuel className="h-3.5 w-3.5" />
                {t('countryExpenses.fuelLiters', { liters: formatLiters(block.fuel_liters) })}
              </p>
            )}
            <p className="mt-1 text-xs text-muted-foreground">{rateNote(t, block)}</p>
          </div>
        );
      })}
    </div>
  );
}
