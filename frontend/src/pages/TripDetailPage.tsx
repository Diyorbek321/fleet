import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, Trash2, FileImage, User, Clock } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

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
  type TripStatus,
  type TripDocument,
} from '@/lib/trips';
import { driversApi } from '@/lib/drivers';
import { ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';
import { TripSubscriptionsCard } from '@/components/trips/TripSubscriptionsCard';
import { TripExpenseReportCard } from '@/components/trips/TripExpenseReportCard';

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

  const [selected, setSelected] = useState<TripDocument | null>(null);

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
            </div>
          </CardContent>
        </Card>
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
