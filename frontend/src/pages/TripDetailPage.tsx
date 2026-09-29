import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, Trash2, FileImage, User, Clock, Pencil, Flag, ClipboardList } from 'lucide-react';
import { format, formatDistanceToNow } from '@/lib/datetime';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  tripsApi,
  listTripDocuments,
  deleteTripDocument,
  type TripCreateInput,
  type TripStatus,
  type TripDocument,
} from '@/lib/trips';
import { useTrucks } from '@/contexts/TruckContext';
import { TripFormDialog } from '@/components/trips/TripFormDialog';
import { driversApi } from '@/lib/drivers';
import { ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';
import { TripSubscriptionsCard } from '@/components/trips/TripSubscriptionsCard';
import { TripExpenseReportCard } from '@/components/trips/TripExpenseReportCard';
import { TripStagePicker } from '@/components/trips/TripStagePicker';
import { CopyTripStatusButton } from '@/components/trips/CopyTripStatusButton';
import { TripOrderButtons } from '@/components/trips/TripOrderButtons';

const UNASSIGNED = '__none__';

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

export default function TripDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { trucks } = useTrucks();
  const [selected, setSelected] = useState<TripDocument | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const tripQuery = useQuery({
    queryKey: ['trip', id],
    queryFn: () => tripsApi.get(id),
    enabled: Boolean(id),
  });

  const docsQuery = useQuery({
    queryKey: ['trip', id, 'documents'],
    queryFn: () => listTripDocuments(id),
    enabled: Boolean(id),
  });

  const driversQuery = useQuery({
    queryKey: ['drivers'],
    queryFn: () => driversApi.list(),
  });

  const assignMutation = useMutation({
    mutationFn: (driverId: string | null) => tripsApi.update(id, { driverId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trip', id] });
      queryClient.invalidateQueries({ queryKey: ['trips'] });
      toast({ title: t('trips.driverAssigned') });
    },
    onError: (err) =>
      toast({ title: t('trips.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const refreshTrip = () => {
    queryClient.invalidateQueries({ queryKey: ['trip', id] });
    queryClient.invalidateQueries({ queryKey: ['trips'] });
  };

  const editMutation = useMutation({
    mutationFn: (input: TripCreateInput) => tripsApi.update(id, input),
    onSuccess: () => {
      setEditOpen(false);
      refreshTrip();
      toast({ title: t('trips.updated') });
    },
    onError: (err) =>
      toast({ title: t('trips.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const deleteMutation = useMutation({
    mutationFn: (docId: string) => deleteTripDocument(id, docId),
    onSuccess: () => {
      setSelected(null);
      queryClient.invalidateQueries({ queryKey: ['trip', id, 'documents'] });
      toast({ title: t('trips.deleted') });
    },
    onError: (err) =>
      toast({ title: t('trips.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const trip = tripQuery.data;
  const documents = docsQuery.data ?? [];

  const statusLabel = (s: TripStatus) => t(`trips.status.${s}`);

  const handleDelete = (doc: TripDocument) => {
    if (window.confirm(t('tripDetail.confirmDelete'))) deleteMutation.mutate(doc.id);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <Button variant="ghost" size="sm" className="gap-1 px-2" onClick={() => navigate('/trips')}>
        <ArrowLeft className="h-4 w-4" />
        {t('tripDetail.back')}
      </Button>

      {/* Trip summary header */}
      {tripQuery.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : tripQuery.isError || !trip ? (
        <p className="text-muted-foreground">{t('trips.empty')}</p>
      ) : (
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <CardTitle className="flex items-center gap-3 text-xl">
                <span className="font-mono">{trip.reference}</span>
                <Badge variant={STATUS_VARIANT[trip.status]}>{statusLabel(trip.status)}</Badge>
              </CardTitle>
              <div className="flex flex-wrap gap-2">
                <CopyTripStatusButton tripId={trip.id} />
                <TripOrderButtons tripId={trip.id} hasTruck={Boolean(trip.truckId)} />
                <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                  <Pencil className="mr-2 h-4 w-4" />
                  {t('common.edit')}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
              <span>{trip.originName ?? '—'}</span>
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
              <span>{trip.destinationName ?? '—'}</span>
            </div>
            <div className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
              <div className="flex items-center gap-2">
                <User className="h-4 w-4 shrink-0 text-muted-foreground" />
                <Select
                  value={trip.driverId ?? UNASSIGNED}
                  onValueChange={(v) => assignMutation.mutate(v === UNASSIGNED ? null : v)}
                  disabled={assignMutation.isPending}
                >
                  <SelectTrigger className="h-8 w-full">
                    <SelectValue placeholder={t('trips.assignDriver')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNASSIGNED}>{t('trips.driverUnassigned')}</SelectItem>
                    {(driversQuery.data ?? []).map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {(trip.truckName || trip.truckPlate) && (
                <div className="flex items-center gap-2 text-muted-foreground">
                  {trip.truckName ?? ''}
                  {trip.truckPlate ? ` (${trip.truckPlate})` : ''}
                </div>
              )}
              {(trip.cargoDescription || trip.cargoWeightKg) && (
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">{t('trips.cargo')}:</span>
                  <span className="font-medium">
                    {[
                      trip.cargoDescription,
                      // Back to tonnes: the column is kilogrammes because the
                      // reports sum it that way, but freight is quoted in
                      // tonnes and that is what was typed in.
                      trip.cargoWeightKg
                        ? `${(trip.cargoWeightKg / 1000).toLocaleString()} ${t('trips.tonsShort')}`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </div>
              )}
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">{t('tripDetail.stage')}:</span>
                <span className="font-medium">
                  {trip.currentStage
                    ? [
                        t(`trips.stage.${trip.currentStage}`),
                        trip.currentStagePlace ? t(`trips.place.${trip.currentStagePlace}`) : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')
                    : t('tripDetail.noStage')}
                </span>
              </div>
              {trip.loadedAt && (
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">{t('tripDetail.loadedAt')}:</span>
                  <span className="font-medium">{format(trip.loadedAt, 'dd.MM.yyyy')}</span>
                </div>
              )}
              {trip.etaCustoms && (
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">{t('tripDetail.etaCustoms')}:</span>
                  <span className="font-medium">{format(trip.etaCustoms, 'dd.MM.yyyy')}</span>
                  <span className="text-xs text-muted-foreground">
                    (
                    {trip.etaBasis === 'history'
                      ? t('tripDetail.etaMeasured')
                      : t('tripDetail.etaModelled')}
                    )
                  </span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {trip && (
        <TripFormDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          trip={trip}
          trucks={trucks}
          drivers={driversQuery.data ?? []}
          isPending={editMutation.isPending}
          onSubmit={(input) => editMutation.mutate(input)}
        />
      )}

      {trip && (
        <div className="grid gap-6 md:grid-cols-2">
          {/* The order sheet, as the driver was sent it */}
          <Card className="border-border/50 bg-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <ClipboardList className="h-5 w-5" />
                {t('trips.form.orderSheet')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-2 text-sm">
                {(
                  [
                    ['direction', trip.direction ? t(`trips.direction.${trip.direction}`) : null],
                    ['borderCrossing', trip.borderCrossing],
                    ['shipper', trip.shipper],
                    ['loadingAddress', trip.loadingAddress],
                    ['loadingDate', trip.scheduledStart ? format(trip.scheduledStart, 'dd.MM.yyyy') : null],
                    ['loadingContact', trip.loadingContact],
                    ['consignee', trip.consignee],
                    ['customsPoint', trip.customsPoint],
                    ['unloadingAddress', trip.unloadingAddress],
                    ['declarantContact', trip.declarantContact],
                    ['notes', trip.notes],
                  ] as const
                ).map(([key, value]) => (
                  <div key={key} className="grid grid-cols-[10rem_1fr] gap-2">
                    <dt className="text-muted-foreground">
                      {key === 'customsPoint' && trip.direction
                        ? t(`trips.form.customsIn.${trip.direction}`)
                        : t(`trips.form.${key}`)}
                    </dt>
                    <dd className="whitespace-pre-line break-words font-medium">{value || '—'}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>

          {/* Report a checkpoint for the driver */}
          <Card className="border-border/50 bg-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Flag className="h-5 w-5" />
                {t('tripDetail.setStage')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <TripStagePicker tripId={trip.id} />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Cargo-owner notifications */}
      {id && <TripSubscriptionsCard tripId={id} />}

      {/* Documents */}
      <Card className="border-border/50 bg-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <FileImage className="h-5 w-5" />
            {t('tripDetail.documents')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {docsQuery.isLoading ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="aspect-square w-full rounded-lg" />
              ))}
            </div>
          ) : documents.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {t('tripDetail.noDocuments')}
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {documents.map((doc) => (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => setSelected(doc)}
                  className="group relative overflow-hidden rounded-lg border border-border/50 bg-muted text-left transition hover:border-primary"
                >
                  <img
                    src={doc.url}
                    alt={doc.caption ?? doc.category}
                    loading="lazy"
                    className="aspect-square w-full object-cover transition group-hover:scale-105"
                  />
                  <Badge variant="secondary" className="absolute left-1.5 top-1.5 capitalize">
                    {doc.category}
                  </Badge>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Driver expense report */}
      {id && <TripExpenseReportCard tripId={id} />}

      {/* Lightbox */}
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Badge variant="secondary" className="capitalize">
                    {selected.category}
                  </Badge>
                </DialogTitle>
              </DialogHeader>
              <img
                src={selected.url}
                alt={selected.caption ?? selected.category}
                className="max-h-[60vh] w-full rounded-lg object-contain"
              />
              <div className="space-y-2 text-sm">
                {selected.caption && <p className="font-medium">{selected.caption}</p>}
                <div className="flex items-center gap-2 text-muted-foreground">
                  <User className="h-4 w-4" />
                  <span>
                    {t('tripDetail.uploadedBy')}: {selected.driverName ?? '—'}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Clock className="h-4 w-4" />
                  <span>{formatDistanceToNow(new Date(selected.uploadedAt), { addSuffix: true })}</span>
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="destructive"
                  disabled={deleteMutation.isPending}
                  onClick={() => handleDelete(selected)}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  {t('tripDetail.delete')}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
