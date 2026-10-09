import type { DriverDocumentField } from '@/lib/drivers';
import { INSURANCE_POLICIES, insuranceState, daysLeft, localToday } from '@/lib/insurance';
import type { TruckDocumentField } from '@/lib/trucks';

/**
 * Every paper the documents page tracks, as columns: what field holds the
 * expiry and which i18n key names it (under `documents.doc`). One expiry date
 * per document, judged by the same 30/7-day thresholds as the insurance.
 */
export interface DocumentColumn<F extends string> {
  field: F;
  labelKey: string;
}

export type TruckColumnField = (typeof INSURANCE_POLICIES)[number]['field'] | TruckDocumentField;

/** Insurance first — one per country — then the rest of the rig's papers. */
export const TRUCK_COLUMNS: readonly DocumentColumn<TruckColumnField>[] = [
  ...INSURANCE_POLICIES.map(({ field, country }) => ({ field, labelKey: `insurance.country.${country}` })),
  { field: 'inspectionExpiry', labelKey: 'documents.doc.inspection' },
  { field: 'permitExpiry', labelKey: 'documents.doc.permit' },
  { field: 'transportLicenseExpiry', labelKey: 'documents.doc.transportLicense' },
  { field: 'certificateExpiry', labelKey: 'documents.doc.truckCertificate' },
  { field: 'tachographExpiry', labelKey: 'documents.doc.tachograph' },
];

export const DRIVER_COLUMNS: readonly DocumentColumn<DriverDocumentField>[] = [
  { field: 'foreignPassportExpiry', labelKey: 'documents.doc.foreignPassport' },
  { field: 'certificateExpiry', labelKey: 'documents.doc.driverCertificate' },
  { field: 'chipCardExpiry', labelKey: 'documents.doc.chipCard' },
  { field: 'licenseExpiry', labelKey: 'documents.doc.license' },
  { field: 'passportExpiry', labelKey: 'documents.doc.passport' },
];

export interface DocumentSummary {
  expired: number;
  soon: number;
  missing: number;
}

type Dated<F extends string> = Partial<Record<F, string | null | undefined>>;

/** Counts documents, not rows: one truck with two lapsed papers is two
 *  things to renew. */
export function summarizeDocuments<F extends string>(
  rows: readonly Dated<F>[],
  columns: readonly DocumentColumn<F>[],
  today: string = localToday(),
): DocumentSummary {
  const summary: DocumentSummary = { expired: 0, soon: 0, missing: 0 };
  for (const row of rows) {
    for (const { field } of columns) {
      const state = insuranceState(row[field], today);
      if (state === 'expired') summary.expired += 1;
      else if (state === 'urgent' || state === 'soon') summary.soon += 1;
      else if (state === 'missing') summary.missing += 1;
    }
  }
  return summary;
}

/** Any document lapsed or within the month. */
export function needsAttention<F extends string>(
  row: Dated<F>,
  columns: readonly DocumentColumn<F>[],
  today: string = localToday(),
): boolean {
  return columns.some(({ field }) => {
    const state = insuranceState(row[field], today);
    return state === 'expired' || state === 'urgent' || state === 'soon';
  });
}

/** Days to the row's nearest-lapsing document, or null when none is entered. */
export function nearestDocumentDays<F extends string>(
  row: Dated<F>,
  columns: readonly DocumentColumn<F>[],
  today: string = localToday(),
): number | null {
  const days = columns
    .map(({ field }) => row[field])
    .filter((v): v is string => !!v)
    .map((v) => daysLeft(v, today));
  return days.length ? Math.min(...days) : null;
}

