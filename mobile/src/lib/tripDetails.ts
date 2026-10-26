/**
 * A trip's details, grouped the way the driver works through a run.
 *
 * The trip card shows the route and the cargo; everything else the dispatcher
 * typed — the customer, the addresses, the contacts, the customs post — used
 * to be on the panel only, and drivers phoned the desk to have it read out.
 * Empty fields are left out rather than shown as dashes: on a phone, a list of
 * dashes hides the three lines that matter.
 */
import { formatDate } from './format';
import type { Trip } from './trips';

export type DetailSectionKey = 'route' | 'loading' | 'unloading' | 'cargo';

export type DetailFieldKey =
  | 'route'
  | 'direction'
  | 'borderCrossing'
  | 'customer'
  | 'shipper'
  | 'loadingAddress'
  | 'loadingContact'
  | 'loadingDate'
  | 'loadedAt'
  | 'consignee'
  | 'unloadingAddress'
  | 'customsPoint'
  | 'declarantContact'
  | 'unloadingDate'
  | 'etaCustoms'
  | 'cargo'
  | 'cargoWeight'
  | 'load'
  | 'reefer';

export interface DetailRow {
  key: DetailFieldKey;
  value: string;
  /** Set when the value holds a phone number the driver can call. */
  phone?: string;
  /** Set when the value is a place the driver can open in a navigator. */
  navigable?: true;
}

export interface DetailSection {
  key: DetailSectionKey;
  rows: DetailRow[];
}

type Translate = (
  key: 'tripDetails.emptyRun' | 'tripDetails.yes' | `tripDetails.directionValue.${'uz_ru' | 'ru_uz'}`,
) => string;

function directionLabel(direction: string | null, t: Translate): string | null {
  return direction === 'uz_ru' || direction === 'ru_uz'
    ? t(`tripDetails.directionValue.${direction}`)
    : null;
}

/** The first phone-like run of digits in free text, ready for a `tel:` link. */
export function phoneIn(text: string): string | null {
  const match = text.match(/\+?\d[\d\s()-]{6,}\d/);
  if (!match) return null;
  const digits = match[0].replace(/[^\d+]/g, '');
  return digits.replace(/\+/g, '').length >= 7 ? digits : null;
}

/**
 * A navigator link for a typed address. `geo:` on Android opens the driver's
 * choice of app — Yandex Navigator, Google Maps, 2GIS — with the address
 * searched; iOS has Apple Maps behind `maps:`.
 */
export function mapsUrl(address: string, platform: string): string {
  const scheme = platform === 'ios' ? 'maps' : 'geo';
  return `${scheme}:0,0?q=${encodeURIComponent(address)}`;
}

type RowKind = 'plain' | 'callable' | 'place';

function rowOf(
  key: DetailFieldKey,
  value: string | null | undefined,
  kind: RowKind = 'plain',
): DetailRow | null {
  const text = value?.trim();
  if (!text) return null;
  if (kind === 'place') return { key, value: text, navigable: true };
  const phone = kind === 'callable' ? phoneIn(text) : null;
  return phone ? { key, value: text, phone } : { key, value: text };
}

function dateOf(iso: string | null | undefined): string | null {
  return iso ? formatDate(iso) : null;
}

function tonnes(kg: number | null | undefined): string | null {
  if (!kg) return null;
  return `${Math.round((kg / 1000) * 100) / 100} t`;
}

export function tripDetailSections(trip: Trip, t: Translate): DetailSection[] {
  const sections: [DetailSectionKey, (DetailRow | null)[]][] = [
    [
      'route',
      [
        rowOf('route', [trip.origin_name, trip.destination_name].filter(Boolean).join(' → ')),
        rowOf('direction', directionLabel(trip.direction, t)),
        rowOf('borderCrossing', trip.border_crossing),
        rowOf('customer', trip.customer),
      ],
    ],
    [
      'loading',
      [
        rowOf('shipper', trip.shipper),
        rowOf('loadingAddress', trip.loading_address, 'place'),
        rowOf('loadingContact', trip.loading_contact, 'callable'),
        rowOf('loadingDate', dateOf(trip.scheduled_start)),
        rowOf('loadedAt', dateOf(trip.loaded_at)),
      ],
    ],
    [
      'unloading',
      [
        rowOf('consignee', trip.consignee),
        rowOf('unloadingAddress', trip.unloading_address, 'place'),
        rowOf('customsPoint', trip.customs_point, 'place'),
        rowOf('declarantContact', trip.declarant_contact, 'callable'),
        rowOf('unloadingDate', dateOf(trip.scheduled_end)),
        rowOf('etaCustoms', dateOf(trip.eta_customs)),
      ],
    ],
    [
      'cargo',
      [
        rowOf('cargo', trip.cargo_description),
        rowOf('cargoWeight', tonnes(trip.cargo_weight_kg)),
        rowOf('load', trip.is_loaded === false ? t('tripDetails.emptyRun') : null),
        rowOf('reefer', trip.is_reefer ? t('tripDetails.yes') : null),
      ],
    ],
    // Not the trip's notes: they are the desk's own (see driver_notices.py).
  ];
  return sections
    .map(([key, rows]) => ({ key, rows: rows.filter((r): r is DetailRow => r !== null) }))
    .filter((s) => s.rows.length > 0);
}
