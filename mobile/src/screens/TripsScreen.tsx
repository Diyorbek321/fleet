import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import * as Location from 'expo-location';

import {
  tripsApi,
  type StagePlace,
  type Trip,
  type TripStage,
  type TripStatus,
} from '../lib/trips';
import { palette, spacing, typography } from '../theme/theme';
import { haptics } from '../lib/haptics';
import { Screen } from '../components/Screen';
import { Button, Card, EmptyState, ErrorBox, Pill } from '../components/ui';
import { StagePicker } from '../components/StagePicker';
import { TripDocuments } from '../components/TripDocuments';
import { TripReportForm } from '../components/TripReportForm';

// Every status the server can send, plus a fallback below: a status added to
// the backend and not yet known here used to index this map to `undefined` and
// take the whole screen down on `sc.color`.
const STATUS_COLOR: Record<TripStatus, { color: string; bg: string }> = {
  draft: { color: palette.faint, bg: palette.surfaceAlt },
  planned: { color: palette.brand, bg: palette.brandLight },
  loading: { color: palette.brand, bg: palette.brandLight },
  en_route: { color: palette.success, bg: palette.successBg },
  at_border: { color: palette.warning, bg: palette.warningBg },
  delivered: { color: palette.success, bg: palette.successBg },
  cancelled: { color: palette.danger, bg: palette.dangerBg },
};

const UNKNOWN_STATUS = { color: palette.faint, bg: palette.surfaceAlt };

export function TripsScreen() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [docsTripId, setDocsTripId] = useState<string | null>(null);
  const [stageTripId, setStageTripId] = useState<string | null>(null);
  const [reportTripId, setReportTripId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const mine = await tripsApi.mine();
      // Guarded, because this screen's whole job here is never to go blank
      // again: anything but a list would throw inside render, past every
      // error branch, and put the driver back in front of a white tab.
      setTrips(Array.isArray(mine) ? mine : []);
      setError(null);
    } catch (e) {
      // Shown on the screen, not only in an alert: an alert is dismissed and
      // leaves the section looking empty, with nothing saying why and no way
      // to try again. This tab reported "not working" for exactly that reason.
      setError(e instanceof Error && e.message ? e.message : t('common.error'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  /** Best-effort GPS pin so border/delivery events are geolocated. Never blocks. */
  const currentCoords = useCallback(async (): Promise<{ lat: number; lng: number } | null> => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') return null;
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      return { lat: pos.coords.latitude, lng: pos.coords.longitude };
    } catch {
      return null;
    }
  }, []);

  const markStage = useCallback(
    async (trip: Trip, stage: TripStage, place: StagePlace) => {
      setBusyId(trip.id);
      void haptics.press();
      try {
        const coords = await currentCoords();
        await tripsApi.advance(trip.id, {
          stage,
          stage_place: place,
          latitude: coords?.lat ?? null,
          longitude: coords?.lng ?? null,
        });
        void haptics.success();
        setStageTripId(null);
        await load();
      } catch (e) {
        // `instanceof Error`, not `instanceof ApiError`: a failure that is not
        // an ApiError is still a failure, and it used to raise an alert with an
        // empty body that told the driver nothing.
        Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
      } finally {
        setBusyId(null);
      }
    },
    [currentCoords, load, t],
  );

  // The screen chrome renders in every state, including the first load. It
  // used to return a bare spinner on a near-white background, so a request
  // that was slow, hung or failing looked identical to a blank screen.
  return (
    <Screen
      title={t('trips.title')}
      subtitle={t('trips.subtitle')}
      icon="cube-outline"
      refreshing={refreshing}
      onRefresh={() => {
        setRefreshing(true);
        load();
      }}
    >
      {error ? (
        <ErrorBox
          message={error}
          onRetry={() => {
            setLoading(true);
            load();
          }}
          retryLabel={t('common.retry')}
        />
      ) : null}
      {loading ? (
        <ActivityIndicator size="large" color={palette.brand} style={styles.spinner} />
      ) : trips.length === 0 && !error ? (
        <EmptyState icon="cube-outline" title={t('trips.empty')} />
      ) : (
        trips.map((trip) => {
          const sc = STATUS_COLOR[trip.status] ?? UNKNOWN_STATUS;
          const stageLabel = trip.current_stage
            ? [
                t(`trips.stage.${trip.current_stage}`),
                trip.current_stage_place ? t(`trips.place.${trip.current_stage_place}`) : null,
              ]
                .filter(Boolean)
                .join(' · ')
            : t('trips.noStageYet');
          return (
            <Card key={trip.id}>
              <View style={styles.row}>
                <Text style={styles.reference}>{trip.reference}</Text>
                <Pill label={t(`trips.status.${trip.status}`)} color={sc.color} bg={sc.bg} />
              </View>
              <Text style={styles.route}>
                {(trip.origin_name ?? '—')} → {(trip.destination_name ?? '—')}
              </Text>
              {trip.cargo_description ? (
                <Text style={styles.cargo}>{trip.cargo_description}</Text>
              ) : null}
              <Text style={styles.stage}>
                {t('trips.currentStage')}: {stageLabel}
              </Text>
              <Button
                label={t('trips.markStage')}
                onPress={() =>
                  setStageTripId((id) => (id === trip.id ? null : trip.id))
                }
                loading={busyId === trip.id}
                icon={stageTripId === trip.id ? 'chevron-up' : 'checkmark-circle-outline'}
              />
              {stageTripId === trip.id ? (
                <StagePicker
                  current={trip.current_stage}
                  busy={busyId === trip.id}
                  onPick={(stage, place) => markStage(trip, stage, place)}
                />
              ) : null}
              <Button
                label={t('trips.documents')}
                onPress={() => setDocsTripId((id) => (id === trip.id ? null : trip.id))}
                variant="ghost"
                icon={docsTripId === trip.id ? 'chevron-up' : 'document-attach-outline'}
              />
              {docsTripId === trip.id ? <TripDocuments tripId={trip.id} /> : null}
              <Button
                label={t('tripReport.toggle')}
                onPress={() => setReportTripId((id) => (id === trip.id ? null : trip.id))}
                variant="ghost"
                icon={reportTripId === trip.id ? 'chevron-up' : 'receipt-outline'}
              />
              {reportTripId === trip.id ? <TripReportForm tripId={trip.id} /> : null}
            </Card>
          );
        })
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  reference: { ...typography.heading, color: palette.ink },
  route: { ...typography.body, marginTop: spacing.xs, color: palette.ink },
  cargo: { ...typography.caption, marginTop: 2 },
  stage: { ...typography.caption, marginTop: spacing.xs, marginBottom: spacing.sm },
  spinner: { marginTop: spacing.xxl },
});
