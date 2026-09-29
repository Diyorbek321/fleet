import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

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
import { TRIP_DIRECTIONS, type Trip, type TripCreateInput, type TripDirection } from '@/lib/trips';
import type { Driver } from '@/lib/drivers';
import type { Truck } from '@/types';

const UNASSIGNED = '__none__';

type TextField =
  | 'originName'
  | 'destinationName'
  | 'borderCrossing'
  | 'shipper'
  | 'loadingAddress'
  | 'loadingContact'
  | 'cargoDescription'
  | 'consignee'
  | 'customsPoint'
  | 'unloadingAddress'
  | 'declarantContact'
  | 'notes';

type FormState = Record<TextField, string> & {
  /** Empty until the dispatcher picks one; a new trip cannot be saved without. */
  direction: TripDirection | '';
  truckId: string;
  driverId: string;
  cargoTons: string;
  /** YYYY-MM-DD from <input type="date">. */
  loadingDate: string;
};

function stateFor(trip: Trip | null): FormState {
  return {
    direction: trip?.direction ?? '',
    truckId: trip?.truckId ?? '',
    driverId: trip?.driverId ?? '',
    originName: trip?.originName ?? '',
    destinationName: trip?.destinationName ?? '',
    borderCrossing: trip?.borderCrossing ?? '',
    shipper: trip?.shipper ?? '',
    loadingAddress: trip?.loadingAddress ?? '',
    loadingContact: trip?.loadingContact ?? '',
    cargoDescription: trip?.cargoDescription ?? '',
    // Tonnes in the form, kilogrammes on the wire — the column is kg because
    // every report sums it that way; freight is quoted in tonnes.
    cargoTons: trip?.cargoWeightKg ? String(trip.cargoWeightKg / 1000) : '',
    loadingDate: trip?.scheduledStart ? trip.scheduledStart.slice(0, 10) : '',
    consignee: trip?.consignee ?? '',
    customsPoint: trip?.customsPoint ?? '',
    unloadingAddress: trip?.unloadingAddress ?? '',
    declarantContact: trip?.declarantContact ?? '',
    notes: trip?.notes ?? '',
  };
}

function tonsToKg(tons: string): number | null {
  const n = Number(tons.replace(',', '.'));
  return tons.trim() && Number.isFinite(n) && n > 0 ? n * 1000 : null;
}

function toInput(form: FormState): TripCreateInput {
  const text = (v: string) => v.trim() || null;
  return {
    direction: form.direction || null,
    truckId: form.truckId || null,
    driverId: form.driverId || null,
    originName: text(form.originName),
    destinationName: text(form.destinationName),
    borderCrossing: text(form.borderCrossing),
    shipper: text(form.shipper),
    loadingAddress: text(form.loadingAddress),
    loadingContact: text(form.loadingContact),
    cargoDescription: text(form.cargoDescription),
    cargoWeightKg: tonsToKg(form.cargoTons),
    // Midnight UTC is the same calendar day in Tashkent (UTC+5).
    scheduledStart: form.loadingDate ? `${form.loadingDate}T00:00:00Z` : null,
    consignee: text(form.consignee),
    customsPoint: text(form.customsPoint),
    unloadingAddress: text(form.unloadingAddress),
    declarantContact: text(form.declarantContact),
    notes: text(form.notes),
  };
}

interface TripFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The trip being edited, or null to create one. */
  trip: Trip | null;
  trucks: Truck[];
  drivers: Driver[];
  isPending: boolean;
  onSubmit: (input: TripCreateInput) => void;
}

/** The order sheet ("заявка") as a form, in the order it is read to a driver:
 *  route, loading, unloading, then who carries it. */
export function TripFormDialog({
  open,
  onOpenChange,
  trip,
  trucks,
  drivers,
  isPending,
  onSubmit,
}: TripFormDialogProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState<FormState>(() => stateFor(trip));
  const [directionMissing, setDirectionMissing] = useState(false);
  const directionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setForm(stateFor(trip));
      setDirectionMissing(false);
    }
  }, [open, trip]);

  // The customs post is in the country the load is going to, so its label
  // names that country once the direction is known.
  const customsLabel = form.direction
    ? t(`trips.form.customsIn.${form.direction}`)
    : t('trips.form.customsPoint');

  const set = (key: keyof FormState) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const field = (
    key: TextField,
    opts: { multiline?: boolean; placeholder?: string; label?: string } = {},
  ) => (
    <div className="space-y-2">
      <Label htmlFor={`trip-${key}`}>{opts.label ?? t(`trips.form.${key}`)}</Label>
      {opts.multiline ? (
        <Textarea
          id={`trip-${key}`}
          rows={2}
          placeholder={opts.placeholder}
          value={form[key]}
          onChange={set(key)}
        />
      ) : (
        <Input
          id={`trip-${key}`}
          placeholder={opts.placeholder}
          value={form[key]}
          onChange={set(key)}
        />
      )}
    </div>
  );

  const section = (title: string) => (
    <h3 className="pt-2 text-sm font-semibold text-muted-foreground">{title}</h3>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{trip ? `${t('trips.edit')} — ${trip.reference}` : t('trips.add')}</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            // Required for a new trip only: trips created before the field
            // existed must stay editable without someone guessing their route.
            if (!trip && !form.direction) {
              setDirectionMissing(true);
              // The picker is at the top of a long form; the save button is at
              // the bottom. Without this the refusal happens off-screen.
              directionRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
              return;
            }
            onSubmit(toInput(form));
          }}
          className="space-y-3"
        >
          {section(t('trips.form.sectionRoute'))}
          <div ref={directionRef} className="space-y-2">
            <Label>{t('trips.form.direction')}</Label>
            <div className="grid grid-cols-2 gap-2">
              {TRIP_DIRECTIONS.map((d) => (
                <Button
                  key={d}
                  type="button"
                  variant={form.direction === d ? 'default' : 'outline'}
                  aria-pressed={form.direction === d}
                  onClick={() => {
                    setForm((f) => ({ ...f, direction: d }));
                    setDirectionMissing(false);
                  }}
                >
                  {t(`trips.direction.${d}`)}
                </Button>
              ))}
            </div>
            {directionMissing && (
              <p className="text-sm text-destructive">{t('trips.form.directionRequired')}</p>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {field('originName', { placeholder: 'Елабуга' })}
            {field('destinationName', { placeholder: 'Ташкент' })}
            {field('borderCrossing', { placeholder: 'Майский' })}
            {field('customsPoint', {
              label: customsLabel,
              placeholder: form.direction
                ? t(`trips.form.customsPlaceholder.${form.direction}`)
                : undefined,
            })}
          </div>

          {section(t('trips.form.sectionLoading'))}
          {field('shipper')}
          {field('loadingAddress', { multiline: true })}
          <div className="grid gap-3 sm:grid-cols-3">
            {field('cargoDescription', { placeholder: 'ДСП' })}
            <div className="space-y-2">
              <Label htmlFor="trip-tons">{t('trips.cargoTons')}</Label>
              <Input
                id="trip-tons"
                inputMode="decimal"
                placeholder={t('trips.cargoTonsPlaceholder')}
                value={form.cargoTons}
                onChange={set('cargoTons')}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="trip-loading-date">{t('trips.form.loadingDate')}</Label>
              <Input
                id="trip-loading-date"
                type="date"
                value={form.loadingDate}
                onChange={set('loadingDate')}
              />
            </div>
          </div>
          {field('loadingContact')}

          {section(t('trips.form.sectionUnloading'))}
          {field('consignee')}
          {field('unloadingAddress', { multiline: true })}
          {field('declarantContact')}

          {section(t('trips.form.sectionAssignment'))}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t('trips.truck')}</Label>
              <Select
                value={form.truckId || UNASSIGNED}
                onValueChange={(v) => setForm((f) => ({ ...f, truckId: v === UNASSIGNED ? '' : v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={UNASSIGNED}>—</SelectItem>
                  {trucks.map((tr) => (
                    <SelectItem key={tr.id} value={tr.id}>
                      {tr.plateNumber}
                      {tr.name && tr.name !== tr.plateNumber ? ` (${tr.name})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('trips.driver')}</Label>
              <Select
                value={form.driverId || UNASSIGNED}
                onValueChange={(v) => setForm((f) => ({ ...f, driverId: v === UNASSIGNED ? '' : v }))}
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

          {field('notes', { multiline: true })}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
