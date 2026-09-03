import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, TriangleAlert } from 'lucide-react';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { COUNTRY_ORDER, type CountryExpenseTrip } from '@/lib/countryExpenses';
import { formatKm } from '@/lib/format';
import { CountryBreakdownTables } from '@/components/reports/CountryBreakdownTables';
import {
  countryLabel,
  countryTotalCell,
  usdMoney,
} from '@/components/reports/countryExpenseLabels';

/**
 * One row per round trip — the shape of the question people actually ask.
 *
 * A truck goes out and comes back; that round trip is the unit an owner judges,
 * not a calendar month. So the row carries the three countries side by side in
 * their own currencies, and opening it shows the same trip itemised: what the
 * money in Kazakhstan went on, what it went on in Russia, and so on.
 *
 * Rows stay collapsed by default. Twenty trips × three countries × a dozen
 * categories is six hundred numbers, and the point of the top-level row is to
 * let someone find the two trips worth opening.
 */
export function CountryTripsTable({ trips }: { trips: CountryExpenseTrip[] }) {
  const { t } = useTranslation();
  const [openTrip, setOpenTrip] = useState<string | null>(null);

  if (trips.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {t('countryExpenses.noTrips')}
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8" />
            <TableHead>{t('countryExpenses.trip')}</TableHead>
            <TableHead>{t('countryExpenses.truck')}</TableHead>
            <TableHead>{t('countryExpenses.date')}</TableHead>
            <TableHead className="text-right">{t('countryExpenses.km')}</TableHead>
            {COUNTRY_ORDER.map((code) => (
              <TableHead key={code} className="text-right">
                {countryLabel(t, code)}
              </TableHead>
            ))}
            <TableHead className="text-right">{t('countryExpenses.totalUsd')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trips.map((trip) => {
            const isOpen = openTrip === trip.trip_id;
            const byCountry = new Map(trip.countries.map((b) => [b.country, b]));

            return (
              <Fragment key={trip.trip_id}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() => setOpenTrip(isOpen ? null : trip.trip_id)}
                >
                  <TableCell className="text-muted-foreground">
                    {isOpen ? (
                      <ChevronDown className="h-4 w-4" />
                    ) : (
                      <ChevronRight className="h-4 w-4" />
                    )}
                  </TableCell>
                  <TableCell>
                    <Link
                      to={`/trips/${trip.trip_id}`}
                      className="font-medium text-primary hover:underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {trip.reference}
                    </Link>
                    {trip.route && (
                      <p className="max-w-[22ch] truncate text-xs text-muted-foreground">
                        {trip.route}
                      </p>
                    )}
                  </TableCell>
                  <TableCell>
                    <span className="font-medium">{trip.plate_number ?? trip.truck_name ?? '—'}</span>
                    {trip.driver_name && (
                      <p className="text-xs text-muted-foreground">{trip.driver_name}</p>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {trip.trip_date ?? '—'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {trip.distance_km ? formatKm(trip.distance_km) : '—'}
                  </TableCell>
                  {COUNTRY_ORDER.map((code) => (
                    <TableCell key={code} className="text-right tabular-nums whitespace-nowrap">
                      {countryTotalCell(byCountry.get(code))}
                    </TableCell>
                  ))}
                  <TableCell className="text-right font-medium tabular-nums whitespace-nowrap">
                    <span className="inline-flex items-center gap-1">
                      {trip.usd_partial && (
                        // The total is short by whatever had no rate. Saying so
                        // on the row is the difference between a cheap trip and
                        // a half-converted one.
                        <TriangleAlert
                          className="h-3.5 w-3.5 text-amber-500"
                          aria-label={t('countryExpenses.partialTotal')}
                        />
                      )}
                      {usdMoney(trip.total_usd)}
                    </span>
                  </TableCell>
                </TableRow>

                {isOpen && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={6 + COUNTRY_ORDER.length} className="bg-muted/30 p-4">
                      <CountryBreakdownTables countries={trip.countries} cards={trip.cards} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
