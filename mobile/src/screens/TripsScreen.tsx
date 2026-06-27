import React, { useCallback, useEffect, useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import * as Location from 'expo-location';

import { ApiError } from '../lib/api';
import { tripsApi, NEXT_STATUS, type Trip, type TripStatus } from '../lib/trips';
import { palette, spacing, typography } from '../theme/theme';
import { haptics } from '../lib/haptics';
import { Screen } from '../components/Screen';
import { Button, Card, EmptyState, Loading, Pill } from '../components/ui';
import { TripDocuments } from '../components/TripDocuments';

const STATUS_COLOR: Record<TripStatus, { color: string; bg: string }> = {
  draft: { color: palette.faint, bg: palette.surfaceAlt },
  planned: { color: palette.brand, bg: palette.brandLight },
  loading: { color: palette.brand, bg: palette.brandLight },
  en_route: { color: palette.success, bg: palette.successBg },
  at_border: { color: palette.warning, bg: palette.warningBg },
  delivered: { color: palette.success, bg: palette.successBg },
  cancelled: { color: palette.danger, bg: palette.dangerBg },
};

export function TripsScreen() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [docsTripId, setDocsTripId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTrips(await tripsApi.mine());
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof ApiError ? e.message : '');
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

  const advance = useCallback(
    async (trip: Trip) => {
      const next = NEXT_STATUS[trip.status];
      if (!next) return;
      setBusyId(trip.id);
      void haptics.press();
      try {
        const coords = await currentCoords();
        await tripsApi.advance(trip.id, {
          to_status: next,
          latitude: coords?.lat ?? null,
          longitude: coords?.lng ?? null,
        });
        void haptics.success();
        await load();
      } catch (e) {
        Alert.alert(t('common.error'), e instanceof ApiError ? e.message : '');
      } finally {
        setBusyId(null);
      }
    },
    [currentCoords, load, t],
  );

  if (loading) return <Loading />;

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
      {trips.length === 0 ? (
        <EmptyState icon="cube-outline" title={t('trips.empty')} />
      ) : (
        trips.map((trip) => {
          const next = NEXT_STATUS[trip.status];
          const sc = STATUS_COLOR[trip.status];
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
              <Text style={styles.rate}>
                {new Intl.NumberFormat('en-US').format(Number(trip.rate))} {trip.currency}
              </Text>
              {next ? (
                <Button
                  label={t('trips.advanceTo', { status: t(`trips.status.${next}`) })}
                  onPress={() => advance(trip)}
                  loading={busyId === trip.id}
                  icon="arrow-forward"
                />
              ) : null}
              <Button
                label={t('trips.documents')}
                onPress={() => setDocsTripId((id) => (id === trip.id ? null : trip.id))}
                variant="ghost"
                icon={docsTripId === trip.id ? 'chevron-up' : 'document-attach-outline'}
              />
              {docsTripId === trip.id ? <TripDocuments tripId={trip.id} /> : null}
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
  rate: { ...typography.heading, color: palette.brand, marginTop: spacing.xs, marginBottom: spacing.sm },
});
