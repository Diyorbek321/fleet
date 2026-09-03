import { useTranslation } from 'react-i18next';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { CardFuel, CountryBlock } from '@/lib/countryExpenses';
import { formatAmount, formatLiters } from '@/lib/format';
import {
  cardLabel,
  categoryLabel,
  countryLabel,
  hasSpending,
  rateNote,
  share,
  usdMoney,
} from '@/components/reports/countryExpenseLabels';

/**
 * What the money in each country actually went on, biggest line first.
 *
 * One table per country rather than a single country × category grid: the
 * categories differ between countries (Platon and AdBlue are meaningless at
 * home; "stoyanka rasmiylashtirish" is an Uzbek line), so a shared grid would
 * be mostly empty cells and imply the blanks are zeros.
 */
export function CountryBreakdownTables({
  countries,
  cards,
}: {
  countries: CountryBlock[];
  cards: CardFuel[];
}) {
  const { t } = useTranslation();
  const spent = countries.filter(hasSpending);

  if (spent.length === 0) return null;

  return (
    <div className="space-y-6">
      {spent.map((block) => (
        <section key={block.country}>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="font-semibold">{countryLabel(t, block.country)}</h4>
            <p className="text-xs text-muted-foreground">{rateNote(t, block)}</p>
          </div>

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('countryExpenses.category')}</TableHead>
                  <TableHead className="text-right">{block.currency}</TableHead>
                  <TableHead className="text-right">USD</TableHead>
                  <TableHead className="text-right">{t('countryExpenses.liters')}</TableHead>
                  <TableHead className="text-right">{t('countryExpenses.share')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {block.lines.map((line) => (
                  <TableRow key={line.category}>
                    <TableCell>{categoryLabel(t, line.category)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatAmount(line.amount)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {usdMoney(line.amount_usd)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {line.liters ? formatLiters(line.liters) : '—'}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {`${Math.round(share(line, block) * 100)}%`}
                    </TableCell>
                  </TableRow>
                ))}
                <TableRow className="font-semibold">
                  <TableCell>{t('countryExpenses.total')}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatAmount(block.total)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {usdMoney(block.total_usd)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {block.fuel_liters ? formatLiters(block.fuel_liters) : '—'}
                  </TableCell>
                  <TableCell />
                </TableRow>
              </TableBody>
            </Table>
          </div>
        </section>
      ))}

      {cards.length > 0 && (
        <section>
          <h4 className="mb-1 font-semibold">{t('countryExpenses.cardsTitle')}</h4>
          {/* Card fuel is settled centrally, so it belongs to no country — said
              out loud, because its absence from the three totals is otherwise
              read as a missing number. */}
          <p className="mb-2 text-xs text-muted-foreground">{t('countryExpenses.cardsHint')}</p>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('countryExpenses.card.title')}</TableHead>
                  <TableHead className="text-right">{t('countryExpenses.amount')}</TableHead>
                  <TableHead className="text-right">{t('countryExpenses.liters')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cards.map((card) => (
                  <TableRow key={card.column}>
                    <TableCell>{cardLabel(t, card.column)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatAmount(card.amount, 2)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatLiters(card.liters)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>
      )}
    </div>
  );
}
