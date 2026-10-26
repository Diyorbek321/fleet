import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Download, Search } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ApiError } from '@/lib/api';
import { formatDistanceToNow } from '@/lib/datetime';
import { fleetBoardApi, type BoardEmpty, type BoardRow, type BoardTrip } from '@/lib/fleetBoard';
import { cn } from '@/lib/utils';
import { toast } from '@/hooks/use-toast';
import { DispatchGroupButton } from './DispatchGroupButton';

type BoardFilter = 'all' | 'export' | 'import' | 'empty' | 'free';

const MATCHES: Record<BoardFilter, (row: BoardRow) => boolean> = {
  all: () => true,
  export: (row) => row.export_trip !== null,
  import: (row) => row.import_trip !== null,
  empty: (row) => row.empty !== null,
  free: (row) => row.export_trip === null && row.import_trip === null,
};

// The hand sheet's colours: the export block green, the import block salmon.
const EXPORT_CELL = 'bg-emerald-500/10';
const IMPORT_CELL = 'bg-orange-500/10';
const COLUMN_COUNT = 11;

/** `2026-10-06` → `06.10.2026`. Split rather than parsed: these are Tashkent
 *  calendar days, and a Date would move them across midnight west of UTC. */
function dmy(day: string | null): string {
  return day ? day.split('-').reverse().join('.') : '';
}

function searchText(row: BoardRow): string {
  return [
    row.plate,
    row.location,
    row.export_trip?.route,
    row.export_trip?.customer,
    row.import_trip?.route,
    row.import_trip?.customer,
    row.empty?.place,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

async function download(onError: (err: unknown) => void) {
  try {
    const { blob, filename } = await fleetBoardApi.xlsx();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err: unknown) {
    onError(err);
  }
}

interface TripCellsProps {
  trip: BoardTrip | null;
  /** Set when the truck stands empty waiting for a load this way. */
  empty: BoardEmpty | null;
  className: string;
}

function EmptyNote({ empty }: { empty: BoardEmpty }) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex flex-col">
      <span className="font-medium text-status-stopped">
        {empty.place ? t('fleetBoard.emptyAt', { place: empty.place }) : t('fleetBoard.emptyNowhere')}
      </span>
      {empty.since && (
        <span className="text-[11px] leading-tight text-muted-foreground">
          {formatDistanceToNow(empty.since, { addSuffix: true })}
        </span>
      )}
    </span>
  );
}

function TripCells({ trip, empty, className }: TripCellsProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const open = trip ? () => navigate(`/trips/${trip.trip_id}`) : undefined;
  const clickable = trip ? 'cursor-pointer hover:underline' : '';
  return (
    <>
      <TableCell className={cn('whitespace-nowrap text-sm', className)}>{trip?.customer}</TableCell>
      <TableCell className={cn('whitespace-nowrap text-sm', className, clickable)} onClick={open}>
        {trip?.route}
        {!trip && empty && <EmptyNote empty={empty} />}
        {trip && !trip.is_loaded && (
          <Badge variant="outline" className="ml-2 border-status-stopped/40 text-status-stopped">
            {t('fleetBoard.empty')}
          </Badge>
        )}
      </TableCell>
      <TableCell className={cn('whitespace-nowrap text-sm', className)}>{dmy(trip?.loading_date ?? null)}</TableCell>
      <TableCell className={cn('whitespace-nowrap text-sm', className)}>
        {trip?.unloading_date && (
          <span className="rounded bg-status-moving/15 px-1.5 py-0.5 font-medium text-status-moving">
            {dmy(trip.unloading_date)}
          </span>
        )}
      </TableCell>
    </>
  );
}

/**
 * Every truck, where the GPS last saw it, and the export and import it is on —
 * the morning sheet the desk used to fill in by phone. Live; the same table
 * goes to the dispatchers' group as an Excel file every morning.
 */
export function FleetBoard() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<BoardFilter>('all');
  const [query, setQuery] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['trips', 'board'],
    queryFn: fleetBoardApi.get,
    refetchInterval: 60_000,
  });

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (data?.rows ?? []).filter(
      (row) => MATCHES[filter](row) && (!needle || searchText(row).includes(needle)),
    );
  }, [data, filter, query]);

  const onDownloadError = (err: unknown) =>
    toast({
      title: t('fleetBoard.downloadFailed'),
      description: err instanceof ApiError ? err.detail : undefined,
      variant: 'destructive',
    });

  const emptyText = (data?.rows.length ?? 0) === 0 ? t('fleetBoard.noTrucks') : t('fleetBoard.noMatch');

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative sm:w-72">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('fleetBoard.search')}
              className="pl-8"
            />
          </div>
          <ToggleGroup
            type="single"
            variant="outline"
            value={filter}
            onValueChange={(v) => v && setFilter(v as BoardFilter)}
            className="flex-wrap justify-start"
          >
            <ToggleGroupItem value="all">{t('fleetBoard.filterAll')}</ToggleGroupItem>
            <ToggleGroupItem value="export">{t('fleetBoard.filterExport')}</ToggleGroupItem>
            <ToggleGroupItem value="import">{t('fleetBoard.filterImport')}</ToggleGroupItem>
            <ToggleGroupItem value="empty">{t('fleetBoard.filterEmpty')}</ToggleGroupItem>
            <ToggleGroupItem value="free">{t('fleetBoard.filterFree')}</ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {data && <span className="text-sm text-muted-foreground">{t('fleetBoard.asOf', { day: dmy(data.day) })}</span>}
          <Button variant="outline" className="gap-2" onClick={() => download(onDownloadError)}>
            <Download className="h-4 w-4" />
            {t('fleetBoard.download')}
          </Button>
          <DispatchGroupButton />
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-card [&_td]:px-3 [&_td]:py-1.5 [&_th]:h-auto [&_th]:px-3 [&_th]:py-2">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead colSpan={3} className="text-center font-semibold">{t('fleetBoard.truck')}</TableHead>
              <TableHead colSpan={4} className={cn('text-center font-semibold', EXPORT_CELL)}>
                {t('fleetBoard.export').toUpperCase()}
              </TableHead>
              <TableHead colSpan={4} className={cn('text-center font-semibold', IMPORT_CELL)}>
                {t('fleetBoard.import').toUpperCase()}
              </TableHead>
            </TableRow>
            <TableRow>
              <TableHead className="w-10">№</TableHead>
              <TableHead>{t('fleetBoard.truckData')}</TableHead>
              <TableHead>{t('fleetBoard.location')}</TableHead>
              <TableHead className={EXPORT_CELL}>{t('fleetBoard.customer')}</TableHead>
              <TableHead className={EXPORT_CELL}>{t('fleetBoard.route')}</TableHead>
              <TableHead className={EXPORT_CELL}>{t('fleetBoard.loadingDate')}</TableHead>
              <TableHead className={EXPORT_CELL}>{t('fleetBoard.unloadingDate')}</TableHead>
              <TableHead className={IMPORT_CELL}>{t('fleetBoard.customer')}</TableHead>
              <TableHead className={IMPORT_CELL}>{t('fleetBoard.route')}</TableHead>
              <TableHead className={IMPORT_CELL}>{t('fleetBoard.loadingDate')}</TableHead>
              <TableHead className={IMPORT_CELL}>{t('fleetBoard.unloadingDate')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={COLUMN_COUNT} className="py-8 text-center text-muted-foreground">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {!isLoading && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={COLUMN_COUNT} className="py-8 text-center text-muted-foreground">
                  {emptyText}
                </TableCell>
              </TableRow>
            )}
            {rows.map((row) => (
              <TableRow key={row.truck_id}>
                <TableCell className="text-xs text-muted-foreground">{row.position}</TableCell>
                <TableCell className="whitespace-nowrap font-mono text-xs font-medium">{row.plate}</TableCell>
                <TableCell className="whitespace-nowrap text-sm">
                  {row.location}
                  {row.location_at && (
                    <div className="text-[11px] leading-tight text-muted-foreground">
                      {t('fleetBoard.gpsAgo', {
                        ago: formatDistanceToNow(row.location_at, { addSuffix: true }),
                      })}
                    </div>
                  )}
                </TableCell>
                <TripCells
                  trip={row.export_trip}
                  empty={row.empty?.kind === 'export' ? row.empty : null}
                  className={EXPORT_CELL}
                />
                <TripCells
                  trip={row.import_trip}
                  empty={row.empty?.kind === 'import' ? row.empty : null}
                  className={IMPORT_CELL}
                />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
