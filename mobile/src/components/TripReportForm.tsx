import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, StyleSheet, Text, TextInput, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import {
  clearTripReportDraft,
  loadTripReportDraft,
  saveTripReportDraft,
  tripReportsApi,
  type TripCountryExpenseLine,
  type TripExpenseReport,
  type TripReportCountry,
  type TripReportExpenseCategory,
  type TripReportInput,
  type TripReportPendingAction,
} from '../lib/tripReports';
import { palette, radius, spacing, typography } from '../theme/theme';
import { Button, Field, Loading, Row } from './ui';

const COUNTRIES: TripReportCountry[] = ['kz', 'ru', 'uz'];

const COUNTRY_CATEGORIES: Record<TripReportCountry, TripReportExpenseCategory[]> = {
  kz: ['platon', 'food', 'traffic_police', 'adblue', 'fine', 'spare_parts', 'repair', 'refund', 'parking', 'phone', 'transport', 'shower'],
  ru: ['platon', 'food', 'traffic_police', 'adblue', 'fine', 'spare_parts', 'repair', 'refund', 'parking', 'phone', 'transport', 'shower'],
  uz: ['groceries', 'fine', 'spare_parts', 'parking_paperwork', 'food', 'taxi', 'carwash', 'repair', 'refund'],
};

type CategoryI18nKey =
  | 'platon'
  | 'food'
  | 'trafficPolice'
  | 'adblue'
  | 'fine'
  | 'spareParts'
  | 'repair'
  | 'refund'
  | 'parking'
  | 'phone'
  | 'transport'
  | 'shower'
  | 'groceries'
  | 'parkingPaperwork'
  | 'taxi'
  | 'carwash';

const CATEGORY_I18N_KEY: Record<TripReportExpenseCategory, CategoryI18nKey> = {
  platon: 'platon',
  food: 'food',
  traffic_police: 'trafficPolice',
  adblue: 'adblue',
  fine: 'fine',
  spare_parts: 'spareParts',
  repair: 'repair',
  refund: 'refund',
  parking: 'parking',
  phone: 'phone',
  transport: 'transport',
  shower: 'shower',
  groceries: 'groceries',
  parking_paperwork: 'parkingPaperwork',
  taxi: 'taxi',
  carwash: 'carwash',
};

function numOrNull(s: string): number | null {
  const trimmed = s.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/** True when the driver typed something that won't parse as a plain number
 *  (a stray letter, or "1,234" with a thousands separator) — used to show
 *  inline feedback instead of letting `numOrNull` silently turn it into
 *  null with no indication anything was dropped. */
function isInvalidNumeric(s: string): boolean {
  return s.trim() !== '' && numOrNull(s) === null;
}

/** Strips anything that can't be part of a plain number as the driver
 *  types, so a thousands separator or stray letter is rejected at the
 *  keystroke — used for the compact fuel-table cells where there isn't
 *  room to show an inline error message under every input. */
function sanitizeNumericInput(raw: string): string {
  let out = '';
  let seenDot = false;
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i];
    if (c >= '0' && c <= '9') {
      out += c;
    } else if (c === '-' && i === 0) {
      out += c;
    } else if (c === '.' && !seenDot) {
      seenDot = true;
      out += c;
    }
  }
  return out;
}

interface FuelRowState {
  row_no: number;
  kz_liters: string;
  kz_amount: string;
  rf_liters: string;
  rf_amount: string;
  doha_liters: string;
  doha_amount: string;
  e1card_liters: string;
  e1card_amount: string;
}

const EMPTY_FUEL_ROW = (rowNo: number): FuelRowState => ({
  row_no: rowNo,
  kz_liters: '',
  kz_amount: '',
  rf_liters: '',
  rf_amount: '',
  doha_liters: '',
  doha_amount: '',
  e1card_liters: '',
  e1card_amount: '',
});

type HeaderState = Record<
  | 'plate_number'
  | 'driver_name'
  | 'report_date'
  | 'route_text'
  | 'exchange_rate_note'
  | 'odometer_out'
  | 'odometer_in'
  | 'fuel_at_garage'
  | 'money_usd'
  | 'money_rub'
  | 'money_kzt'
  | 'money_uzs'
  | 'usd_to_kzt_given'
  | 'usd_to_kzt_received'
  | 'usd_to_rub_given'
  | 'usd_to_rub_received'
  | 'electronic_pass_note'
  | 'electronic_queue_note'
  | 'insurance_rf'
  | 'insurance_kz'
  | 'dollar_return'
  | 'driver_comment',
  string
>;

const EMPTY_HEADER: HeaderState = {
  plate_number: '',
  driver_name: '',
  report_date: '',
  route_text: '',
  exchange_rate_note: '',
  odometer_out: '',
  odometer_in: '',
  fuel_at_garage: '',
  money_usd: '',
  money_rub: '',
  money_kzt: '',
  money_uzs: '',
  usd_to_kzt_given: '',
  usd_to_kzt_received: '',
  usd_to_rub_given: '',
  usd_to_rub_received: '',
  electronic_pass_note: '',
  electronic_queue_note: '',
  insurance_rf: '',
  insurance_kz: '',
  dollar_return: '',
  driver_comment: '',
};

function reportToHeader(r: TripExpenseReport): HeaderState {
  const s = (v: number | string | null) => (v === null || v === undefined ? '' : String(v));
  return {
    plate_number: r.plate_number ?? '',
    driver_name: r.driver_name ?? '',
    report_date: r.report_date ?? '',
    route_text: r.route_text ?? '',
    exchange_rate_note: r.exchange_rate_note ?? '',
    odometer_out: s(r.odometer_out),
    odometer_in: s(r.odometer_in),
    fuel_at_garage: s(r.fuel_at_garage),
    money_usd: s(r.money_usd),
    money_rub: s(r.money_rub),
    money_kzt: s(r.money_kzt),
    money_uzs: s(r.money_uzs),
    usd_to_kzt_given: s(r.usd_to_kzt_given),
    usd_to_kzt_received: s(r.usd_to_kzt_received),
    usd_to_rub_given: s(r.usd_to_rub_given),
    usd_to_rub_received: s(r.usd_to_rub_received),
    electronic_pass_note: r.electronic_pass_note ?? '',
    electronic_queue_note: r.electronic_queue_note ?? '',
    insurance_rf: s(r.insurance_rf),
    insurance_kz: s(r.insurance_kz),
    dollar_return: s(r.dollar_return),
    driver_comment: r.driver_comment ?? '',
  };
}

function countryKey(country: TripReportCountry, category: TripReportExpenseCategory): string {
  return `${country}:${category}`;
}

/** Everything the form needs to fully reconstruct its state — persisted to
 *  AsyncStorage so a driver's in-progress report survives an app kill,
 *  backgrounding, or a failed save/submit at a border crossing with no
 *  signal. Deliberately a plain snapshot of component state, not the API
 *  payload shape (`TripReportInput`), so unparsed/invalid text the driver
 *  typed round-trips exactly instead of being lost to `numOrNull`. */
interface FormDraft {
  header: HeaderState;
  fuelRows: FuelRowState[];
  countryAmounts: Record<string, string>;
  borderDepartureAt: string | null;
  borderArrivalAt: string | null;
}

/** A `Field` for numeric entry that shows an inline error instead of
 *  silently letting an unparsable value (a stray letter, "1,234") get
 *  discarded as null on save. */
function NumericField({
  label,
  value,
  onChangeText,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
}) {
  const { t } = useTranslation();
  const invalid = isInvalidNumeric(value);
  return (
    <View style={{ gap: 4 }}>
      <Field
        label={label}
        value={value}
        onChangeText={onChangeText}
        keyboardType="numeric"
        style={invalid ? styles.inputError : undefined}
      />
      {invalid ? <Text style={styles.fieldError}>{t('tripReport.validation.invalidNumber')}</Text> : null}
    </View>
  );
}

/** Inline "yo'l varaqasi" form — mirrors the paper report a driver fills per trip.
 *  Toggled open from a trip card, like `TripDocuments`. Explicit Save/Submit
 *  buttons hit the server (so a flaky connection can't silently half-save),
 *  but every edit is also debounce-saved to an on-device draft — and saved
 *  again immediately if a Save/Submit call fails — so nothing typed at a
 *  signal-less border crossing is ever lost to a dropped connection. */
export function TripReportForm({ tripId }: { tripId: string }) {
  const { t } = useTranslation();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<'draft' | 'submitted'>('draft');
  const [totals, setTotals] = useState<TripExpenseReport['totals'] | null>(null);

  const [header, setHeader] = useState<HeaderState>(EMPTY_HEADER);
  const [fuelRows, setFuelRows] = useState<FuelRowState[]>([1, 2, 3, 4].map(EMPTY_FUEL_ROW));
  const [countryAmounts, setCountryAmounts] = useState<Record<string, string>>({});
  const [borderDepartureAt, setBorderDepartureAt] = useState<string | null>(null);
  const [borderArrivalAt, setBorderArrivalAt] = useState<string | null>(null);

  // What the driver was last trying to do when a network call failed —
  // drives the "not yet synced" banner and the single automatic retry
  // below. Null once everything is confirmed saved on the server.
  const [pendingAction, setPendingAction] = useState<TripReportPendingAction>(null);
  const [draftRestored, setDraftRestored] = useState(false);

  // Guards the draft-autosave effect so it can't fire (and stomp a real
  // draft with blank defaults) before the initial load — server fetch plus
  // local-draft restore — has finished.
  const loadedRef = useRef(false);
  const draftDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let fetchFailed = false;
      try {
        const report = await tripReportsApi.get(tripId);
        if (cancelled) return;
        if (report) {
          setHeader(reportToHeader(report));
          setStatus(report.status);
          setTotals(report.totals);
          setBorderDepartureAt(report.border_departure_at);
          setBorderArrivalAt(report.border_arrival_at);
          if (report.fuel_rows.length) {
            setFuelRows(
              report.fuel_rows.map((r) => ({
                row_no: r.row_no,
                kz_liters: r.kz_liters === null ? '' : String(r.kz_liters),
                kz_amount: r.kz_amount === null ? '' : String(r.kz_amount),
                rf_liters: r.rf_liters === null ? '' : String(r.rf_liters),
                rf_amount: r.rf_amount === null ? '' : String(r.rf_amount),
                doha_liters: r.doha_liters === null ? '' : String(r.doha_liters),
                doha_amount: r.doha_amount === null ? '' : String(r.doha_amount),
                e1card_liters: r.e1card_liters === null ? '' : String(r.e1card_liters),
                e1card_amount: r.e1card_amount === null ? '' : String(r.e1card_amount),
              })),
            );
          }
          const amounts: Record<string, string> = {};
          for (const line of report.country_expenses) {
            amounts[countryKey(line.country, line.category)] = String(line.amount);
          }
          setCountryAmounts(amounts);
        }
      } catch {
        // Likely offline — don't alert yet. If a local draft exists below,
        // silently restoring it is the right outcome; only alert if there's
        // truly nothing to fall back to.
        fetchFailed = true;
      }
      if (cancelled) return;

      // A local draft always wins over the server value here: it only
      // exists because either an edit was made after the last successful
      // save, or a save/submit attempt failed outright — either way it is
      // the more recent, not-yet-synced state.
      const draft = await loadTripReportDraft<FormDraft>(tripId);
      if (cancelled) return;
      if (draft) {
        setHeader(draft.data.header);
        setFuelRows(draft.data.fuelRows);
        setCountryAmounts(draft.data.countryAmounts);
        setBorderDepartureAt(draft.data.borderDepartureAt);
        setBorderArrivalAt(draft.data.borderArrivalAt);
        setDraftRestored(true);
        if (draft.pendingAction) setPendingAction(draft.pendingAction);
      } else if (fetchFailed) {
        Alert.alert(t('common.error'), t('tripReport.offline.loadFailed'));
      }

      loadedRef.current = true;
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [tripId, t]);

  const setField = useCallback(
    (key: keyof HeaderState) => (value: string) => setHeader((h) => ({ ...h, [key]: value })),
    [],
  );

  const setFuelCell = useCallback(
    (rowIndex: number, key: keyof FuelRowState) => (value: string) =>
      setFuelRows((rows) =>
        rows.map((r, i) => (i === rowIndex ? { ...r, [key]: sanitizeNumericInput(value) } : r)),
      ),
    [],
  );

  const addFuelRow = useCallback(() => {
    setFuelRows((rows) => [...rows, EMPTY_FUEL_ROW(rows.length + 1)]);
  }, []);

  const setCountryAmount = useCallback((key: string, value: string) => {
    setCountryAmounts((prev) => ({ ...prev, [key]: value }));
  }, []);

  // Debounced local-draft autosave: fires on every field edit (after the
  // initial load has settled) so the driver's typed data lives somewhere
  // more durable than component state before they ever hit Save.
  useEffect(() => {
    if (!loadedRef.current) return;
    if (draftDebounceRef.current) clearTimeout(draftDebounceRef.current);
    draftDebounceRef.current = setTimeout(() => {
      void saveTripReportDraft<FormDraft>(
        tripId,
        { header, fuelRows, countryAmounts, borderDepartureAt, borderArrivalAt },
        pendingAction,
      );
    }, 600);
    return () => {
      if (draftDebounceRef.current) clearTimeout(draftDebounceRef.current);
    };
  }, [tripId, header, fuelRows, countryAmounts, borderDepartureAt, borderArrivalAt, pendingAction]);

  const buildPayload = useCallback((): TripReportInput => {
    const country_expenses: TripCountryExpenseLine[] = [];
    for (const country of COUNTRIES) {
      for (const category of COUNTRY_CATEGORIES[country]) {
        const raw = countryAmounts[countryKey(country, category)];
        const amount = raw ? numOrNull(raw) : null;
        if (amount !== null) country_expenses.push({ country, category, amount });
      }
    }
    return {
      plate_number: header.plate_number || null,
      driver_name: header.driver_name || null,
      report_date: header.report_date || null,
      route_text: header.route_text || null,
      exchange_rate_note: header.exchange_rate_note || null,
      odometer_out: numOrNull(header.odometer_out),
      odometer_in: numOrNull(header.odometer_in),
      fuel_at_garage: numOrNull(header.fuel_at_garage),
      money_usd: numOrNull(header.money_usd),
      money_rub: numOrNull(header.money_rub),
      money_kzt: numOrNull(header.money_kzt),
      money_uzs: numOrNull(header.money_uzs),
      usd_to_kzt_given: numOrNull(header.usd_to_kzt_given),
      usd_to_kzt_received: numOrNull(header.usd_to_kzt_received),
      usd_to_rub_given: numOrNull(header.usd_to_rub_given),
      usd_to_rub_received: numOrNull(header.usd_to_rub_received),
      border_departure_at: borderDepartureAt,
      border_arrival_at: borderArrivalAt,
      electronic_pass_note: header.electronic_pass_note || null,
      electronic_queue_note: header.electronic_queue_note || null,
      insurance_rf: numOrNull(header.insurance_rf),
      insurance_kz: numOrNull(header.insurance_kz),
      dollar_return: numOrNull(header.dollar_return),
      driver_comment: header.driver_comment || null,
      fuel_rows: fuelRows.map((r) => ({
        row_no: r.row_no,
        kz_liters: numOrNull(r.kz_liters),
        kz_amount: numOrNull(r.kz_amount),
        rf_liters: numOrNull(r.rf_liters),
        rf_amount: numOrNull(r.rf_amount),
        doha_liters: numOrNull(r.doha_liters),
        doha_amount: numOrNull(r.doha_amount),
        e1card_liters: numOrNull(r.e1card_liters),
        e1card_amount: numOrNull(r.e1card_amount),
      })),
      country_expenses,
    };
  }, [header, fuelRows, countryAmounts, borderDepartureAt, borderArrivalAt]);

  const currentDraftData = useCallback(
    (): FormDraft => ({ header, fuelRows, countryAmounts, borderDepartureAt, borderArrivalAt }),
    [header, fuelRows, countryAmounts, borderDepartureAt, borderArrivalAt],
  );

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const saved = await tripReportsApi.save(tripId, buildPayload());
      setStatus(saved.status);
      setTotals(saved.totals);
      setPendingAction(null);
      setDraftRestored(false);
      await saveTripReportDraft<FormDraft>(tripId, currentDraftData(), null);
      Alert.alert(t('tripReport.saved'));
    } catch {
      // Offline or the server is unreachable: the debounced autosave above
      // already keeps writing on every edit, but write once more right now
      // (with the failed action recorded) so a kill immediately after this
      // failure can't race the debounce and lose the attempt.
      setPendingAction('save');
      await saveTripReportDraft<FormDraft>(tripId, currentDraftData(), 'save');
      Alert.alert(t('tripReport.offline.savedLocallyTitle'), t('tripReport.offline.savedLocallyMessage'));
    } finally {
      setSaving(false);
    }
  }, [tripId, buildPayload, currentDraftData, t]);

  const submit = useCallback(async () => {
    setSaving(true);
    try {
      await tripReportsApi.save(tripId, buildPayload());
      const submitted = await tripReportsApi.submit(tripId);
      setStatus(submitted.status);
      setTotals(submitted.totals);
      setPendingAction(null);
      setDraftRestored(false);
      await clearTripReportDraft(tripId);
      Alert.alert(t('tripReport.submitted'));
    } catch {
      setPendingAction('submit');
      await saveTripReportDraft<FormDraft>(tripId, currentDraftData(), 'submit');
      Alert.alert(t('tripReport.offline.savedLocallyTitle'), t('tripReport.offline.submitPendingMessage'));
    } finally {
      setSaving(false);
    }
  }, [tripId, buildPayload, currentDraftData, t]);

  // A single automatic retry the moment a pending save/submit shows up —
  // covers the mount-restore case (a draft left over from a failed attempt
  // last session). Intentionally does not re-run on every keystroke: it
  // fires once when `pendingAction` transitions to a new value, capturing
  // whatever `buildPayload` produces at that moment. Further edits keep
  // being autosaved locally as normal; the next real retry is either this
  // effect (next time pendingAction changes) or the driver tapping
  // Save/Submit again.
  useEffect(() => {
    if (!pendingAction || !loadedRef.current) return;
    let cancelled = false;
    (async () => {
      try {
        const saved = await tripReportsApi.save(tripId, buildPayload());
        if (cancelled) return;
        setStatus(saved.status);
        setTotals(saved.totals);
        if (pendingAction === 'submit') {
          const submitted = await tripReportsApi.submit(tripId);
          if (cancelled) return;
          setStatus(submitted.status);
          setTotals(submitted.totals);
          await clearTripReportDraft(tripId);
        } else {
          await saveTripReportDraft<FormDraft>(tripId, currentDraftData(), null);
        }
        if (!cancelled) {
          setPendingAction(null);
          setDraftRestored(false);
        }
      } catch {
        // Still unreachable — stays pending until the next mount or a
        // manual Save/Submit tap.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAction, tripId]);

  const statusLabel = useMemo(
    () => (status === 'submitted' ? t('tripReport.statusSubmitted') : t('tripReport.statusDraft')),
    [status, t],
  );

  if (loading) return <Loading />;

  return (
    <View style={styles.wrap}>
      <Text style={styles.statusText}>{statusLabel}</Text>

      {pendingAction && (
        <View style={styles.pendingBanner}>
          <Text style={styles.pendingBannerText}>
            {pendingAction === 'submit'
              ? t('tripReport.offline.pendingSubmitBanner')
              : t('tripReport.offline.pendingSaveBanner')}
          </Text>
        </View>
      )}
      {!pendingAction && draftRestored && (
        <Text style={styles.restoredBannerText}>{t('tripReport.offline.restoredBanner')}</Text>
      )}

      {/* Header */}
      <Text style={styles.section}>{t('tripReport.header.title')}</Text>
      <Field label={t('tripReport.header.plate')} value={header.plate_number} onChangeText={setField('plate_number')} />
      <Field label={t('tripReport.header.driverName')} value={header.driver_name} onChangeText={setField('driver_name')} />
      <Field label={t('tripReport.header.date')} value={header.report_date} onChangeText={setField('report_date')} placeholder="YYYY-MM-DD" />
      <Field label={t('tripReport.header.route')} value={header.route_text} onChangeText={setField('route_text')} />
      <NumericField label={t('tripReport.header.odometerOut')} value={header.odometer_out} onChangeText={setField('odometer_out')} />
      <NumericField label={t('tripReport.header.odometerIn')} value={header.odometer_in} onChangeText={setField('odometer_in')} />
      <NumericField label={t('tripReport.header.fuelAtGarage')} value={header.fuel_at_garage} onChangeText={setField('fuel_at_garage')} />
      <Field label={t('tripReport.header.exchangeNote')} value={header.exchange_rate_note} onChangeText={setField('exchange_rate_note')} />

      {/* Money issued */}
      <Text style={styles.section}>{t('tripReport.money.title')}</Text>
      <NumericField label={t('tripReport.money.usd')} value={header.money_usd} onChangeText={setField('money_usd')} />
      <NumericField label={t('tripReport.money.rub')} value={header.money_rub} onChangeText={setField('money_rub')} />
      <NumericField label={t('tripReport.money.kzt')} value={header.money_kzt} onChangeText={setField('money_kzt')} />
      <NumericField label={t('tripReport.money.uzs')} value={header.money_uzs} onChangeText={setField('money_uzs')} />
      <NumericField label={t('tripReport.money.toKztGiven')} value={header.usd_to_kzt_given} onChangeText={setField('usd_to_kzt_given')} />
      <NumericField label={t('tripReport.money.toKztReceived')} value={header.usd_to_kzt_received} onChangeText={setField('usd_to_kzt_received')} />
      <NumericField label={t('tripReport.money.toRubGiven')} value={header.usd_to_rub_given} onChangeText={setField('usd_to_rub_given')} />
      <NumericField label={t('tripReport.money.toRubReceived')} value={header.usd_to_rub_received} onChangeText={setField('usd_to_rub_received')} />

      {/* Fuel table */}
      <Text style={styles.section}>{t('tripReport.fuel.title')}</Text>
      {fuelRows.map((row, i) => (
        <View key={row.row_no} style={styles.fuelRow}>
          <Text style={styles.fuelRowLabel}>{t('tripReport.fuel.row')} {row.row_no}</Text>
          <View style={styles.fuelGrid}>
            {(
              [
                ['kz', 'kz_liters', 'kz_amount'],
                ['rf', 'rf_liters', 'rf_amount'],
                ['doha', 'doha_liters', 'doha_amount'],
                ['e1card', 'e1card_liters', 'e1card_amount'],
              ] as const
            ).map(([col, litersKey, amountKey]) => (
              <View key={col} style={styles.fuelCol}>
                <Text style={styles.fuelColLabel}>{t(`tripReport.fuel.${col}`)}</Text>
                <TextInput
                  style={styles.miniInput}
                  placeholder={t('tripReport.fuel.liters')}
                  placeholderTextColor={palette.faint}
                  keyboardType="numeric"
                  value={row[litersKey]}
                  onChangeText={setFuelCell(i, litersKey)}
                />
                <TextInput
                  style={styles.miniInput}
                  placeholder={t('tripReport.fuel.amount')}
                  placeholderTextColor={palette.faint}
                  keyboardType="numeric"
                  value={row[amountKey]}
                  onChangeText={setFuelCell(i, amountKey)}
                />
              </View>
            ))}
          </View>
        </View>
      ))}
      <Button label={t('tripReport.fuel.addRow')} variant="ghost" icon="add" onPress={addFuelRow} />
      {totals && (
        <Text style={styles.totalText}>
          {t('tripReport.fuel.total')}: {totals.fuel_liters_total.toLocaleString()} L /{' '}
          {totals.fuel_amount_total.toLocaleString()}
        </Text>
      )}

      {/* Border crossing */}
      <Text style={styles.section}>{t('tripReport.border.title')}</Text>
      <View style={styles.borderRow}>
        <Button
          label={borderDepartureAt ? new Date(borderDepartureAt).toLocaleString() : t('tripReport.border.departure')}
          variant="outline"
          icon="log-out-outline"
          onPress={() => setBorderDepartureAt(new Date().toISOString())}
        />
        <Button
          label={borderArrivalAt ? new Date(borderArrivalAt).toLocaleString() : t('tripReport.border.arrival')}
          variant="outline"
          icon="log-in-outline"
          onPress={() => setBorderArrivalAt(new Date().toISOString())}
        />
      </View>
      <Field label={t('tripReport.border.electronicPass')} value={header.electronic_pass_note} onChangeText={setField('electronic_pass_note')} />
      <Field label={t('tripReport.border.electronicQueue')} value={header.electronic_queue_note} onChangeText={setField('electronic_queue_note')} />

      {/* Per-country expenses */}
      <Text style={styles.section}>{t('tripReport.countries.title')}</Text>
      {COUNTRIES.map((country) => (
        <View key={country} style={styles.countryBlock}>
          <Text style={styles.countryTitle}>{t(`tripReport.countries.${country}`)}</Text>
          {COUNTRY_CATEGORIES[country].map((category) => {
            const key = countryKey(country, category);
            return (
              <NumericField
                key={key}
                label={t(`tripReport.countries.category.${CATEGORY_I18N_KEY[category]}`)}
                value={countryAmounts[key] ?? ''}
                onChangeText={(v) => setCountryAmount(key, v)}
              />
            );
          })}
          {totals && (
            <Text style={styles.totalText}>
              {t('tripReport.countries.subtotal')}: {(totals.country_totals[country] ?? 0).toLocaleString()}
            </Text>
          )}
        </View>
      ))}

      {/* Footer */}
      <Text style={styles.section}>{t('tripReport.footer.title')}</Text>
      <NumericField label={t('tripReport.footer.insuranceRf')} value={header.insurance_rf} onChangeText={setField('insurance_rf')} />
      <NumericField label={t('tripReport.footer.insuranceKz')} value={header.insurance_kz} onChangeText={setField('insurance_kz')} />
      <NumericField label={t('tripReport.footer.dollarReturn')} value={header.dollar_return} onChangeText={setField('dollar_return')} />
      <Field label={t('tripReport.footer.comment')} value={header.driver_comment} onChangeText={setField('driver_comment')} multiline />

      {/* Currency balances — money issued vs. spent, so a driver can see at
          a glance whether their reported numbers reconcile. */}
      {totals && (
        <View style={styles.countryBlock}>
          <Text style={styles.section}>{t('tripReport.balances.title')}</Text>
          {(['usd', 'rub', 'kzt', 'uzs'] as const).map((currency) => (
            <Row
              key={currency}
              label={t(`tripReport.money.${currency}`)}
              value={totals.currency_balances[currency].toLocaleString()}
            />
          ))}
        </View>
      )}

      <View style={styles.actions}>
        <Button label={t('tripReport.save')} icon="save-outline" onPress={save} loading={saving} style={styles.actionBtn} />
        <Button label={t('tripReport.submit')} icon="send-outline" variant="success" onPress={submit} loading={saving} style={styles.actionBtn} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: spacing.sm,
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: palette.line,
  },
  statusText: { ...typography.label, color: palette.brand },
  section: { ...typography.heading, marginTop: spacing.sm },
  fuelRow: { gap: spacing.xs },
  fuelRowLabel: { ...typography.label },
  fuelGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  fuelCol: { minWidth: 80, flexGrow: 1, gap: 4 },
  fuelColLabel: { ...typography.caption, fontWeight: '700' },
  miniInput: {
    borderWidth: 1,
    borderColor: palette.line,
    backgroundColor: palette.surfaceAlt,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 6,
    fontSize: 13,
    color: palette.ink,
  },
  totalText: { ...typography.caption, fontWeight: '700', color: palette.ink },
  borderRow: { flexDirection: 'row', gap: spacing.sm },
  countryBlock: { gap: spacing.xs, marginTop: spacing.xs },
  countryTitle: { ...typography.label, fontWeight: '700' },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  actionBtn: { flex: 1 },
  inputError: { borderColor: palette.danger },
  fieldError: { ...typography.caption, color: palette.danger },
  pendingBanner: {
    backgroundColor: palette.dangerBg,
    borderWidth: 1,
    borderColor: palette.dangerLine,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  pendingBannerText: { ...typography.caption, color: palette.danger, fontWeight: '700' },
  restoredBannerText: { ...typography.caption, color: palette.muted },
});
