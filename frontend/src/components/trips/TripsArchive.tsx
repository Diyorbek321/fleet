import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useInfiniteQuery } from '@tanstack/react-query';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { tripsApi, type Trip, type TripDirection } from '@/lib/trips';
import { format } from '@/lib/datetime';
import { formatTripRate } from '@/lib/format';

/** Export leaves Uzbekistan, import comes home. `all` also holds the trips
 *  with no direction on file, which neither filter can claim. */
type ArchiveFilter = 'all' | 'export' | 'import';

const FILTER_DIRECTION: Record<ArchiveFilter, TripDirection | undefined> = {
  all: undefined,
  export: 'uz_ru',
  import: 'ru_uz',
};

const EMPTY_KEY: Record<ArchiveFilter, string> = {
  all: 'trips.archive.empty',
  export: 'trips.archive.emptyExport',
  import: 'trips.archive.emptyImport',
};

const PAGE_SIZE = 100;

interface TripsArchiveProps {
  truckLabel: (trip: Trip) => string;
}

export function TripsArchive({ truckLabel }: TripsArchiveProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<ArchiveFilter>('all');
  const direction = FILTER_DIRECTION[filter];

  const { data, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['trips', 'archive', direction ?? 'all'],
    queryFn: ({ pageParam }) =>
      tripsApi.list({ archived: true, direction, limit: PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) =>
      last.length === PAGE_SIZE ? pages.length * PAGE_SIZE : undefined,
  });
  const trips = data?.pages.flat() ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted-foreground">{t('trips.archive.hint')}</p>
        <ToggleGroup
          type="single"
          variant="outline"
          value={filter}
          // Radix clears the value when the active item is clicked again;
          // the archive always shows one of the three.
          onValueChange={(v) => v && setFilter(v as ArchiveFilter)}
        >
          <ToggleGroupItem value="all">{t('trips.archive.all')}</ToggleGroupItem>
          <ToggleGroupItem value="export">
            {t('trips.archive.export')}
            <span className="ml-1 text-xs text-muted-foreground">{t('trips.directionShort.uz_ru')}</span>
          </ToggleGroupItem>
          <ToggleGroupItem value="import">
            {t('trips.archive.import')}
            <span className="ml-1 text-xs text-muted-foreground">{t('trips.directionShort.ru_uz')}</span>
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      <div className="rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('trips.reference')}</TableHead>
              <TableHead>{t('trips.route')}</TableHead>
              <TableHead>{t('trips.truck')}</TableHead>
              <TableHead>{t('trips.rate')}</TableHead>
              <TableHead>{t('trips.archive.deliveredAt')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {!isLoading && trips.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  {t(EMPTY_KEY[filter])}
                </TableCell>
              </TableRow>
            )}
            {trips.map((trip) => (
              <TableRow key={trip.id} className="cursor-pointer" onClick={() => navigate(`/trips/${trip.id}`)}>
                <TableCell className="font-mono text-xs font-medium">{trip.reference}</TableCell>
                <TableCell className="text-sm">
                  {(trip.originName ?? '—')} → {(trip.destinationName ?? '—')}
                  {trip.direction && (
                    <Badge variant="secondary" className="ml-2">
                      {t(`trips.directionShort.${trip.direction}`)}
                    </Badge>
                  )}
                  {!trip.isLoaded && (
                    <Badge variant="outline" className="ml-2 border-status-stopped/40 text-status-stopped">
                      {t('trips.emptyRun')}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-sm">{truckLabel(trip)}</TableCell>
                <TableCell className="text-sm">{formatTripRate(trip.rate, trip.currency)}</TableCell>
                <TableCell className="text-sm">
                  {trip.deliveredAt ? format(trip.deliveredAt, 'dd.MM.yyyy') : '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {hasNextPage && (
        <div className="flex justify-center">
          <Button variant="outline" disabled={isFetchingNextPage} onClick={() => fetchNextPage()}>
            {t('trips.archive.loadMore')}
          </Button>
        </div>
      )}
    </div>
  );
}
