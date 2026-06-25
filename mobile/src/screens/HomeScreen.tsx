import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, StyleSheet, Switch, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import * as Location from 'expo-location';

import { meApi, type AssignedTruck, type Shift } from '../lib/me';
import {
  isTrackingActive,
  requestTrackingPermissions,
  startBackgroundTracking,
  stopBackgroundTracking,
} from '../lib/location-task';
import { formatDateTime } from '../lib/format';
import { palette, spacing, typography } from '../theme/theme';
import { Screen } from '../components/Screen';
import {
  Button,
  Card,
  EmptyState,
  Field,
  IconCircle,
  Loading,
  Pill,
  Row,
  SectionHeader,
  StatTile,
} from '../components/ui';

export function HomeScreen() {
  const { t } = useTranslation();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [truck, setTruck] = useState<AssignedTruck | null>(null);
  const [shift, setShift] = useState<Shift | null>(null);
  const [odometer, setOdometer] = useState('');
  const [busy, setBusy] = useState(false);

  const [sharing, setSharing] = useState(false);
  // Foreground-only subscription, used as a fallback when the OS denies
  // background location permission.
  const subRef = useRef<Location.LocationSubscription | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, s] = await Promise.all([meApi.assignment(), meApi.currentShift()]);
      setTruck(a);
      setShift(s);
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    load();
    // Reflect any already-running background tracking (e.g. after the app was
    // reopened mid-shift) in the toggle.
    isTrackingActive().then(setSharing).catch(() => {});
    return () => {
      subRef.current?.remove();
    };
  }, [load]);

  const toShift = useCallback(
    async (fn: () => Promise<Shift>) => {
      setBusy(true);
      try {
        setShift(await fn());
        setOdometer('');
      } catch (e) {
        Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
      } finally {
        setBusy(false);
      }
    },
    [t],
  );

  const odo = () => (odometer.trim() ? Number(odometer) : null);

  // Foreground-only fallback: pings while the app is open, used when the OS
  // grants foreground but denies background location permission.
  const startForegroundWatch = useCallback(async () => {
    subRef.current = await Location.watchPositionAsync(
      { accuracy: Location.Accuracy.Balanced, timeInterval: 15000, distanceInterval: 50 },
      (loc) => {
        meApi
          .pingLocation({
            latitude: loc.coords.latitude,
            longitude: loc.coords.longitude,
            speed: loc.coords.speed ?? 0,
            heading: loc.coords.heading ?? null,
          })
          .catch(() => {});
      },
    );
  }, []);

  const stopForegroundWatch = useCallback(() => {
    subRef.current?.remove();
    subRef.current = null;
  }, []);

  const toggleSharing = useCallback(
    async (value: boolean) => {
      if (value) {
        try {
          const permission = await requestTrackingPermissions();
          if (permission === 'denied') {
            Alert.alert(t('tracking.permissionNeeded'));
            return;
          }
          if (permission === 'granted-background') {
            // True always-on tracking via the OS background task.
            await startBackgroundTracking();
          } else {
            // Foreground granted only: keep working while the app is open and
            // tell the driver background tracking is unavailable.
            await startForegroundWatch();
            Alert.alert(t('tracking.title'), t('tracking.foregroundOnly'));
          }
          setSharing(true);
        } catch (e) {
          Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
        }
      } else {
        try {
          await stopBackgroundTracking();
        } catch {
          // Ignore: nothing to stop if it was never started.
        }
        stopForegroundWatch();
        setSharing(false);
      }
    },
    [startForegroundWatch, stopForegroundWatch, t],
  );

  if (loading) return <Loading />;

  const subtitle = shift
    ? t('home.shiftSince', { time: formatDateTime(shift.started_at) })
    : t('home.startShift');

  return (
    <Screen
      eyebrow={t('home.welcome')}
      title={t('tabs.home')}
      subtitle={subtitle}
      refreshing={refreshing}
      onRefresh={() => {
        setRefreshing(true);
        load();
      }}
    >
      {truck ? (
        <>
          <View style={styles.statRow}>
            <StatTile
              icon="speedometer"
              value={`${Math.round(truck.fuel_level)}%`}
              label={t('home.fuelLevel')}
              color={palette.fuel}
              bg={palette.fuelBg}
            />
            <StatTile
              icon="navigate"
              value={`${Math.round(truck.mileage).toLocaleString()}`}
              label={`${t('home.mileage')} (${t('common.km')})`}
              color={palette.mileage}
              bg={palette.mileageBg}
            />
          </View>

          <Card>
            <View style={styles.truckRow}>
              <IconCircle icon="bus" color={palette.brand} bg={palette.brandLight} size={48} />
              <View style={styles.truckText}>
                <Text style={styles.truckName}>{truck.name}</Text>
                <Text style={styles.truckPlate}>{truck.plate_number}</Text>
              </View>
            </View>
          </Card>
        </>
      ) : (
        <Card>
          <EmptyState icon="bus-outline" title={t('home.noTruck')} />
        </Card>
      )}

      <Card>
        <SectionHeader
          icon={shift ? 'pulse' : 'play'}
          title={shift ? t('home.shiftActive') : t('home.startShift')}
          color={shift ? palette.success : palette.brand}
          bg={shift ? palette.successBg : palette.brandLight}
          right={shift ? <Pill label={t('home.shiftActive')} color={palette.success} bg={palette.successBg} /> : undefined}
        />
        {shift ? (
          <>
            <Row label={t('home.shiftActive')} value={formatDateTime(shift.started_at)} />
            <Field
              label={t('home.endMileage')}
              icon="navigate-outline"
              value={odometer}
              onChangeText={setOdometer}
              keyboardType="numeric"
              placeholder="0"
            />
            <Button
              label={t('home.endShift')}
              icon="stop-circle-outline"
              variant="danger"
              loading={busy}
              onPress={() => toShift(() => meApi.endShift(odo()))}
            />
          </>
        ) : (
          <>
            <Field
              label={t('home.startMileage')}
              icon="navigate-outline"
              value={odometer}
              onChangeText={setOdometer}
              keyboardType="numeric"
              placeholder="0"
            />
            <Button
              label={t('home.startShift')}
              icon="play-circle-outline"
              loading={busy}
              onPress={() => toShift(() => meApi.startShift(odo()))}
            />
          </>
        )}
      </Card>

      <Card>
        <SectionHeader
          icon="location"
          title={t('tracking.title')}
          color={sharing ? palette.success : palette.muted}
          bg={sharing ? palette.successBg : palette.surfaceAlt}
        />
        <View style={styles.shareRow}>
          <Text style={[typography.body, sharing && styles.liveText]}>
            {sharing ? t('tracking.on') : t('tracking.off')}
          </Text>
          <Switch
            value={sharing}
            onValueChange={toggleSharing}
            trackColor={{ false: palette.line, true: palette.brand }}
            thumbColor={palette.white}
          />
        </View>
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  statRow: { flexDirection: 'row', gap: spacing.md },
  truckRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  truckText: { flex: 1, gap: 2 },
  truckName: typography.heading,
  truckPlate: { ...typography.label, color: palette.muted, letterSpacing: 1 },
  shareRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  liveText: { color: palette.success, fontWeight: '700' },
});
