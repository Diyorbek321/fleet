import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, ArrowRight } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { tripsApi, type Trip, type TripStatus } from '@/lib/trips';
import { driversApi } from '@/lib/drivers';
import { ApiError } from '@/lib/api';
import { useTrucks } from '@/contexts/TruckContext';
import { toast } from '@/hooks/use-toast';

const UNASSIGNED = '__none__';

const TRIPS_KEY = ['trips'] as const;

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

function fmtMoney(amount: number, currency: string): string {
  return `${new Intl.NumberFormat('en-US').format(amount)} ${currency}`;
}

export default function TripsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { trucks } = useTrucks();
  const queryClient = useQueryClient();

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({
    truckId: '',
    driverId: '',
    shipper: '',
    consignee: '',
    originName: '',
    destinationName: '',
    cargoDescription: '',
    rate: '',
    currency: 'UZS',
    isReefer: false,
    notes: '',
  });

  const { data: trips = [], isLoading } = useQuery({
    queryKey: TRIPS_KEY,
    queryFn: () => tripsApi.list(),
    refetchInterval: 30_000,
  });

  const { data: drivers = [] } = useQuery({
    queryKey: ['drivers'],
    queryFn: () => driversApi.list(),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: TRIPS_KEY });

  const createMutation = useMutation({
    mutationFn: tripsApi.create,
    onSuccess: () => {
      setCreateOpen(false);
      setForm({
        truckId: '',
        driverId: '',
        shipper: '',
        consignee: '',
        originName: '',
        destinationName: '',
        cargoDescription: '',
        rate: '',
        currency: 'UZS',
        isReefer: false,
        notes: '',
      });
      invalidate();
      toast({ title: t('trips.created') });
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

  const truckLabel = (trip: Trip) => {
    const tr = trucks.find((x) => x.id === trip.truckId);
    return tr ? `${tr.name} (${tr.plateNumber})` : '—';
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('trips.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('trips.subtitle')}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('trips.add')}
        </Button>
      </div>

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
                    {trip.isReefer && (
                      <Badge variant="outline" className="ml-2">
                        {t('trips.reefer')}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">{truckLabel(trip)}</TableCell>
                  <TableCell className="text-sm">{fmtMoney(trip.rate, trip.currency)}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[trip.status]}>{statusLabel(trip.status)}</Badge>
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

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('trips.add')}</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate({
                truckId: form.truckId || undefined,
                driverId: form.driverId || undefined,
                shipper: form.shipper.trim() || undefined,
                consignee: form.consignee.trim() || undefined,
                originName: form.originName.trim() || undefined,
                destinationName: form.destinationName.trim() || undefined,
                cargoDescription: form.cargoDescription.trim() || undefined,
                rate: form.rate ? Number(form.rate) : undefined,
                currency: form.currency,
                isReefer: form.isReefer,
                notes: form.notes.trim() || undefined,
              });
            }}
            className="space-y-3"
          >
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>{t('trips.shipper')}</Label>
                <Input value={form.shipper} onChange={(e) => setForm({ ...form, shipper: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t('trips.consignee')}</Label>
                <Input value={form.consignee} onChange={(e) => setForm({ ...form, consignee: e.target.value })} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>{t('trips.origin')}</Label>
                <Input value={form.originName} onChange={(e) => setForm({ ...form, originName: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label>{t('trips.destination')}</Label>
                <Input
                  value={form.destinationName}
                  onChange={(e) => setForm({ ...form, destinationName: e.target.value })}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>{t('trips.truck')}</Label>
                <Select value={form.truckId} onValueChange={(v) => setForm({ ...form, truckId: v })}>
                  <SelectTrigger>
                    <SelectValue placeholder="—" />
                  </SelectTrigger>
                  <SelectContent>
                    {trucks.map((tr) => (
                      <SelectItem key={tr.id} value={tr.id}>
                        {tr.name} ({tr.plateNumber})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t('trips.driver')}</Label>
                <Select
                  value={form.driverId || UNASSIGNED}
                  onValueChange={(v) => setForm({ ...form, driverId: v === UNASSIGNED ? '' : v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="—" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNASSIGNED}>{t('trips.driverUnassigned')}</SelectItem>
                    {drivers.map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t('trips.cargo')}</Label>
              <Input
                value={form.cargoDescription}
                onChange={(e) => setForm({ ...form, cargoDescription: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>{t('trips.rate')}</Label>
                <Input
                  type="number"
                  min={0}
                  value={form.rate}
                  onChange={(e) => setForm({ ...form, rate: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label>{t('trips.currency')}</Label>
                <Select value={form.currency} onValueChange={(v) => setForm({ ...form, currency: v })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="UZS">UZS</SelectItem>
                    <SelectItem value="USD">USD</SelectItem>
                    <SelectItem value="RUB">RUB</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.isReefer}
                onChange={(e) => setForm({ ...form, isReefer: e.target.checked })}
              />
              {t('trips.reeferCargo')}
            </label>
            <div className="space-y-2">
              <Label>{t('trips.notes')}</Label>
              <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
