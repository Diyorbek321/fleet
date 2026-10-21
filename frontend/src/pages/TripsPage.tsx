import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, ArrowRight, Flag, Archive, Truck as TruckIcon, Table2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { placeKey, tripsApi, type Trip, type TripCreateInput, type TripStatus } from '@/lib/trips';
import { TripFormDialog } from '@/components/trips/TripFormDialog';
import { TripStagePicker } from '@/components/trips/TripStagePicker';
import { CopyTripStatusButton } from '@/components/trips/CopyTripStatusButton';
import { TripsArchive } from '@/components/trips/TripsArchive';
import { FleetBoard } from '@/components/trips/FleetBoard';
import { formatTripRate } from '@/lib/format';
import { ApiError } from '@/lib/api';
import { useTrucks } from '@/contexts/TruckContext';
import { toast } from '@/hooks/use-toast';

const TRIPS_KEY = ['trips'] as const;
// Delivered trips live in the archive tab; the board is the work still moving.
const ACTIVE_TRIPS_KEY = ['trips', 'active'] as const;

type Tab = 'active' | 'board' | 'archive';

const STATUS_FLOW: Record<TripStatus, TripStatus | null> = {
  draft: 'planned',
  planned: 'loading',
  loading: 'en_route',
  en_route: 'at_border',
  at_border: 'delivered',
  delivered: null,
  cancelled: null,
};

const STATUS_VARIANT: Record<TripStatus, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  draft: 'outline',
  planned: 'secondary',
  loading: 'secondary',
  en_route: 'default',
  at_border: 'destructive',
  delivered: 'default',
  cancelled: 'outline',
};

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function TripsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { trucks } = useTrucks();
  const queryClient = useQueryClient();

  // `editing` is null while creating; one dialog serves both.
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Trip | null>(null);
  // The one row whose checkpoint picker is open; saving closes it.
  const [stageTripId, setStageTripId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('active');

  const { data: trips = [], isLoading } = useQuery({
    queryKey: ACTIVE_TRIPS_KEY,
    queryFn: () => tripsApi.list({ archived: false }),
    refetchInterval: 30_000,
    enabled: tab === 'active',
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: TRIPS_KEY });

  const saveMutation = useMutation({
    mutationFn: (input: TripCreateInput) =>
      editing ? tripsApi.update(editing.id, input) : tripsApi.create(input),
    onSuccess: (saved) => {
      setFormOpen(false);
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['trip', saved.id] });
      toast({ title: editing ? t('trips.updated') : t('trips.created') });
    },
    onError: (err) =>
      toast({ title: t('trips.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const advanceMutation = useMutation({
    mutationFn: ({ id, to }: { id: string; to: TripStatus }) => tripsApi.advance(id, to),
    onSuccess: () => {
      invalidate();
      toast({ title: t('trips.advanced') });
    },
    onError: (err) =>
      toast({ title: t('trips.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const removeMutation = useMutation({
    mutationFn: tripsApi.remove,
    onSuccess: () => {
      invalidate();
      toast({ title: t('trips.deleted') });
    },
    onError: (err) =>
      toast({ title: t('trips.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const statusLabel = (s: TripStatus) => t(`trips.status.${s}`);

  const truckById = useMemo(() => new Map(trucks.map((tr) => [tr.id, tr])), [trucks]);

  const truckLabel = (trip: Trip) => {
    const tr = truckById.get(trip.truckId);
    return tr ? `${tr.name} (${tr.plateNumber})` : '—';
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('trips.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('trips.subtitle')}</p>
        </div>
        <Button
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          {t('trips.add')}
        </Button>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsList>
          <TabsTrigger value="active" className="gap-2">
            <TruckIcon className="h-4 w-4" />
            {t('trips.tabActive')}
          </TabsTrigger>
          <TabsTrigger value="board" className="gap-2">
            <Table2 className="h-4 w-4" />
            {t('fleetBoard.tab')}
          </TabsTrigger>
          <TabsTrigger value="archive" className="gap-2">
            <Archive className="h-4 w-4" />
            {t('trips.tabArchive')}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === 'board' && <FleetBoard />}
      {tab === 'archive' && <TripsArchive truckLabel={truckLabel} />}
      {tab === 'active' && (
        <div className="rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('trips.reference')}</TableHead>
                <TableHead>{t('trips.route')}</TableHead>
                <TableHead>{t('trips.truck')}</TableHead>
                <TableHead>{t('trips.rate')}</TableHead>
                <TableHead>{t('trips.statusLabel')}</TableHead>
                <TableHead className="w-[1%]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    {t('common.loading')}
                  </TableCell>
                </TableRow>
              )}
              {!isLoading && trips.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    {t('trips.empty')}
                  </TableCell>
                </TableRow>
              )}
              {trips.map((trip) => {
                const next = STATUS_FLOW[trip.status];
                return (
                  <TableRow
                    key={trip.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/trips/${trip.id}`)}
                  >
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
                      {trip.isReefer && (
                        <Badge variant="outline" className="ml-2">
                          {t('trips.reefer')}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{truckLabel(trip)}</TableCell>
                    <TableCell className="text-sm">{formatTripRate(trip.rate, trip.currency)}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[trip.status]}>{statusLabel(trip.status)}</Badge>
                      {trip.currentStage && (
                        <div className="mt-1 text-xs text-muted-foreground">
                          {t(`trips.stage.${trip.currentStage}`)}
                          {trip.currentStagePlace ? ` · ${t(placeKey(trip.currentStagePlace, trip.direction))}` : ''}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                      {next && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="gap-1"
                          disabled={advanceMutation.isPending}
                          onClick={(e) => {
                            e.stopPropagation();
                            advanceMutation.mutate({ id: trip.id, to: next });
                          }}
                          title={`${statusLabel(trip.status)} → ${statusLabel(next)}`}
                        >
                          <ArrowRight className="h-4 w-4" />
                          {statusLabel(next)}
                        </Button>
                      )}
                      <Popover
                        open={stageTripId === trip.id}
                        onOpenChange={(open) => setStageTripId(open ? trip.id : null)}
                      >
                        <PopoverTrigger asChild>
                          <Button variant="ghost" size="icon" title={t('tripDetail.setStage')}>
                            <Flag className="h-4 w-4" />
                          </Button>
                        </PopoverTrigger>
                        <PopoverContent align="end" className="w-72" onClick={(e) => e.stopPropagation()}>
                          <p className="mb-3 text-sm font-medium">
                            {t('tripDetail.setStage')} · <span className="font-mono">{trip.reference}</span>
                          </p>
                          <TripStagePicker tripId={trip.id} direction={trip.direction} onSaved={() => setStageTripId(null)} />
                        </PopoverContent>
                      </Popover>
                      <CopyTripStatusButton tripId={trip.id} variant="ghost" iconOnly />
                      <Button
                        variant="ghost"
                        size="icon"
                        title={t('common.edit')}
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditing(trip);
                          setFormOpen(true);
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (window.confirm(t('trips.confirmDelete'))) removeMutation.mutate(trip.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <TripFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        trip={editing}
        trucks={trucks}
        isPending={saveMutation.isPending}
        onSubmit={(input) => saveMutation.mutate(input)}
      />
    </div>
  );
}
