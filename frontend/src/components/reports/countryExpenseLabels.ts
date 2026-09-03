import type { TFunction } from 'i18next';

import type { CategoryLine, CountryBlock, CountryCode } from '@/lib/countryExpenses';
import { formatAmount } from '@/lib/format';

/**
 * Labels shared by every view of the country-expense report.
 *
 * Country and category names are reused from the `tripReport` namespace rather
 * than duplicated: the words come off the same paper form the driver fills in,
 * and two copies of them would eventually disagree about what "Платон" is
 * called here versus on the trip page.
 */

export const countryLabel = (t: TFunction, country: CountryCode): string =>
  t(`tripReport.countries.${country}`);

export const categoryLabel = (t: TFunction, category: string): string => {
  const key = category.replace(/_([a-z])/g, (_, ch: string) => ch.toUpperCase());
  return t(`tripReport.countries.category.${key}`);
};

export const cardLabel = (t: TFunction, column: string): string =>
  t(`countryExpenses.card.${column}`, { defaultValue: column.toUpperCase() });

/** An amount with the currency it was actually paid in, e.g. "140 400 KZT". */
export const nativeMoney = (amount: number, currency: string): string =>
  `${formatAmount(amount)} ${currency}`;

/**
 * One country's cell on a trip row.
 *
 * The currency travels with the number because the three cells sit side by side
 * and hold three different ones — an unlabelled column of digits invites the
 * reader to compare them, which is exactly what they must not do.
 */
export const countryTotalCell = (block: CountryBlock | undefined): string =>
  !block || block.total === 0 ? '—' : nativeMoney(block.total, block.currency);

/**
 * A USD figure, or a dash when there was no rate.
 *
 * The dash is load-bearing: it says "not converted". A zero here would read as
 * "spent nothing", which is the one thing a missing rate never means.
 */
export const usdMoney = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : `$${formatAmount(value, 2)}`;

/** "1 USD = 520.00 KZT (reys kursi)" — where a converted figure came from. */
export function rateNote(t: TFunction, block: CountryBlock): string {
  if (!block.rate) return t('countryExpenses.noRate');
  const source = block.rate_source
    ? t(`countryExpenses.rateSource.${block.rate_source}`)
    : t('countryExpenses.rateSource.org');
  return t('countryExpenses.rateNote', {
    rate: formatAmount(block.rate, 2),
    currency: block.currency,
    source,
  });
}

/** A line's share of its country's spending, as a fraction of 1. */
export const share = (line: CategoryLine, block: CountryBlock): number =>
  block.total > 0 ? line.amount / block.total : 0;

export const hasSpending = (block: CountryBlock): boolean =>
  block.total > 0 || block.fuel_liters > 0;
