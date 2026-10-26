import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Alert, Linking, Platform, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import * as Location from 'expo-location';
import * as Notifications from 'expo-notifications';

import { meApi, type AssignedTruck, type DriverMessage, type Shift } from '../lib/me';
import { askToEnableGps, checkGpsServices } from '../lib/gps-watch';
import { requestTrackingPermissions } from '../lib/location-task';
import { keepTrackingAlive, type TrackingState } from '../lib/tracking-keeper';
import { TRACKING_DEPS } from '../lib/tracking-os';
import { useAuth } from '../contexts/AuthContext';
import { confirmLocationDisclosure, needsDisclosure } from '../lib/location-disclosure';
import { formatDateTime } from '../lib/format';
import { loadErrorMessage } from '../lib/load-error';
import { deliverFix, fixFrom } from '../lib/ping-queue';
import { phoneState } from '../lib/phone-state';
import { palette, spacing, typography } from '../theme/theme';
import { RussiaStayCard } from '../components/RussiaStayCard';
import { Screen } from '../components/Screen';
import { MessagesCard } from '../components/MessagesCard';
import { PhoneSetupCard } from '../components/PhoneSetupCard';
import {
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  IconCircle,
  Loading,
  Pill,
  Row,
  SectionHeader,
  StatTile,
} from '../components/ui';

// How often we re-check the OS tracking state while the app is open. The
// background task can silently stop itself (e.g. a dead session — see
// location-task.ts) without the app ever being notified, so it is re-checked
// and restarted rather than trusted from a single mount-time read.
const SHARING_RESYNC_INTERVAL_MS = 60_000;

/** What the warning card says and offers, per reason sharing is not live. */
const TRACKING_COPY = {
  'needs-permission': {
    body: 'tracking.mustEnableBody',
    action: 'tracking.enable',
  },
  'needs-always': {
    body: 'tracking.needsAlways',
    action: 'tracking.openSettings',
  },
  'signed-out': { body: 'tracking.signedOut', action: 'tracking.signInAgain' },
} as const;


export function HomeScreen() {
  const { t } = useTranslation();
  const { signOut } = useAuth();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // Bumped on pull-to-refresh so the cards that load themselves reload too.
  const [refreshKey, setRefreshKey] = useState(0);
  const [truck, setTruck] = useState<AssignedTruck | null>(null);
  const [shift, setShift] = useState<Shift | null>(null);
  // Null truck/shift are only meaningful after a load succeeded: before that
  // they mean "unknown", and rendering "No truck assigned" and a "Start shift"
  // form on a failed load told drivers their truck had been taken away (and
  // invited a duplicate shift).
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [odometer, setOdometer] = useState('');
  const [busy, setBusy] = useState(false);

  // Optimistic: the warning card must not flash on every open before the
  // first check confirms tracking is running.
  const [tracking, setTracking] = useState<TrackingState>('live');
  const [gpsOn, setGpsOn] = useState(true);
  const [messages, setMessages] = useState<DriverMessage[]>([]);
  // Foreground-only subscription, used as a fallback when the OS denies
  // background location permission.
  const subRef = useRef<Location.LocationSubscription | null>(null);
  // Set once `startForegroundWatch` exists; the sync below runs before it.
  const startForegroundWatchRef = useRef<() => Promise<void>>(async () => {});
  const watchStartingRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const [a, s] = await Promise.all([meApi.assignment(), meApi.currentShift()]);
      setTruck(a);
      setShift(s);
      setLoaded(true);
      setLoadError(null);
    } catch (e) {
      // Inline with a retry button rather than an alert: a dropped connection
      // is routine on the road, and the alert blocked the screen behind it.
      setLoadError(loadErrorMessage(e, t));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  // The inbox is loaded apart from the rest: a failure here must not put an
  // error dialog in front of the shift controls.
  const loadMessages = useCallback(() => {
    meApi.messages().then(setMessages).catch(() => {});
  }, []);

  const markRead = useCallback(
    (id: string) => {
      meApi
        .markMessageRead(id)
        .then((updated) => setMessages((prev) => prev.map((m) => (m.id === id ? updated : m))))
        .catch(() => {});
    },
    [],
  );

  // Not just a read: tracking stopped by the OS, a reboot or a dead session
  // is restarted here whenever "always" is still granted. There is no off
  // switch — sharing is switched on once and stays on.
  const syncSharingState = useCallback(() => {
    keepTrackingAlive(TRACKING_DEPS)
      .then((state) => {
        setTracking(state);
        // While-in-use only: still report while the app is open. Any other
        // state drops that watch — once "always" is granted the background
        // task reports, and two reporters would double every ping.
        if (state === 'needs-always') {
          startForegroundWatchRef.current().catch(() => {});
        } else {
          subRef.current?.remove();
          subRef.current = null;
        }
      })
      // A check that cannot finish must not leave the green card up.
      .catch(() => setTracking('needs-permission'));
    checkGpsServices().then(setGpsOn);
  }, []);

  useEffect(() => {
    load();
    loadMessages();
    // Reflect any already-running background tracking (e.g. after the app was
    // reopened mid-shift) in the toggle.
    syncSharingState();
    return () => {
      subRef.current?.remove();
    };
  }, [load, loadMessages, syncSharingState]);

  // A message pushed while the app is open shows up in the inbox right away.
  useEffect(() => {
    const sub = Notifications.addNotificationReceivedListener((n) => {
      if (n.request.content.data?.kind === 'message') loadMessages();
    });
    return () => sub.remove();
  }, [loadMessages]);

  // Re-sync whenever the app returns to the foreground — the most likely
  // moment for tracking to have died while backgrounded — and on a periodic
  // interval as a backstop for while the app stays open/foregrounded.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        syncSharingState();
        loadMessages();
        // The truck and shift too: the dispatcher may have changed them while
        // the app was in the background, and a load that failed offline
        // recovers on its own once the driver comes back to the app.
        load();
      }
    });
    const interval = setInterval(syncSharingState, SHARING_RESYNC_INTERVAL_MS);
    return () => {
      subscription.remove();
      clearInterval(interval);
    };
  }, [syncSharingState, loadMessages, load]);

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
    // The mount, foreground and interval checks can all land before the first
    // watch resolves; the flag keeps them from starting a second one.
    if (subRef.current || watchStartingRef.current) return;
    watchStartingRef.current = true;
    try {
      subRef.current = await Location.watchPositionAsync(
        // Same sampling as the background task, for the same heartbeat reason.
        { accuracy: Location.Accuracy.Balanced, timeInterval: 15000, distanceInterval: 0 },
        (loc) => {
          const fix = fixFrom(loc);
          phoneState('foreground')
            .then((state) => deliverFix(fix, (points) => meApi.pingLocations(points, state)))
            .catch(() => {});
        },
      );
    } finally {
      watchStartingRef.current = false;
    }
  }, []);

  startForegroundWatchRef.current = startForegroundWatch;

  // The one-time "switch it on". After this, `syncSharingState` keeps it on.
  const enableTracking = useCallback(async () => {
    try {
      if (tracking === 'signed-out') {
        // Back to the login screen; signing in clears the flag.
        await signOut();
        return;
      }
      if (tracking === 'needs-always') {
        // The OS will not show the prompt a second time; only Settings can.
        await Linking.openSettings();
        return;
      }
      const background = await Location.getBackgroundPermissionsAsync();
      if (
        needsDisclosure(Platform.OS, background.status) &&
        !(await confirmLocationDisclosure(t))
      ) {
        return;
      }
      const permission = await requestTrackingPermissions();
      if (permission === 'denied') {
        Alert.alert(t('tracking.permissionNeeded'));
      } else if (permission === 'granted-foreground-only') {
        Alert.alert(t('tracking.title'), t('tracking.foregroundOnly'));
      }
      syncSharingState();
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    }
  }, [tracking, syncSharingState, signOut, t]);

  if (loading) return <Loading />;

  const subtitle = !loaded
    ? undefined
    : shift
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
        setRefreshKey((k) => k + 1);
        load();
        loadMessages();
      }}
    >
      {!gpsOn && (
        <Card style={styles.gpsCard}>
          <SectionHeader
            icon="warning"
            title={t('gps.offTitle')}
            color={palette.danger}
            bg={palette.dangerBg}
          />
          <Text style={typography.body}>{t('gps.offBody')}</Text>
          <Button
            label={t('gps.turnOn')}
            icon="locate-outline"
            variant="danger"
            onPress={() => askToEnableGps().then(syncSharingState)}
          />
        </Card>
      )}

      {tracking !== 'live' && (
        <Card style={styles.gpsCard}>
          <SectionHeader
            icon="location"
            title={t('tracking.mustEnableTitle')}
            color={palette.danger}
            bg={palette.dangerBg}
          />
          <Text style={typography.body}>{t(TRACKING_COPY[tracking].body)}</Text>
          <Button
            label={t(TRACKING_COPY[tracking].action)}
            icon="locate-outline"
            variant="danger"
            onPress={enableTracking}
          />
        </Card>
      )}

      {/* Once sharing is on: the phone settings that keep it on with the app closed. */}
      {tracking === 'live' && <PhoneSetupCard />}

      {loadError ? (
        <ErrorBox
          message={loadError}
          onRetry={() => {
            setRefreshing(true);
            load();
            loadMessages();
          }}
          retryLabel={t('common.retry')}
        />
      ) : null}

      <MessagesCard messages={messages} onRead={markRead} />

      <RussiaStayCard refreshKey={refreshKey} />

      {!loaded ? null : truck ? (
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

      {loaded && (
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
      )}

      {/* Status only: sharing has no off switch. */}
      {tracking === 'live' && (
        <Card>
          <SectionHeader
            icon="location"
            title={t('tracking.title')}
            color={palette.success}
            bg={palette.successBg}
          />
          <Text style={[typography.body, styles.liveText]}>{t('tracking.on')}</Text>
        </Card>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  statRow: { flexDirection: 'row', gap: spacing.md },
  truckRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  truckText: { flex: 1, gap: 2 },
  truckName: typography.heading,
  truckPlate: { ...typography.label, color: palette.muted, letterSpacing: 1 },
  liveText: { color: palette.success, fontWeight: '700' },
  gpsCard: { borderWidth: 1, borderColor: palette.dangerLine, gap: spacing.md },
});
