import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Linking, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { ApiError } from '../lib/api';
import { queueApi, type QueueStatus, type QueueStatusValue, type QueueWatch } from '../lib/queue';
import { palette, spacing, typography } from '../theme/theme';
import { Screen } from '../components/Screen';
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
} from '../components/ui';

/** Status → semantic color + tinted background for the queue Pill. */
const STATUS_STYLE: Record<QueueStatusValue, { color: string; bg: string }> = {
  in_queue: { color: palette.brand, bg: palette.brandLight },
  late: { color: palette.warning, bg: palette.warningBg },
  crossed: { color: palette.success, bg: palette.successBg },
  check_failed: { color: palette.danger, bg: palette.dangerBg },
  revoked: { color: palette.danger, bg: palette.dangerBg },
  none: { color: palette.muted, bg: palette.surfaceAlt },
  unknown: { color: palette.muted, bg: palette.surfaceAlt },
};

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function QueueScreen() {
  const { t } = useTranslation();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [noTruck, setNoTruck] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [status, setStatus] = useState<QueueStatus | null>(null);
  const [watch, setWatch] = useState<QueueWatch | null>(null);

  const [checkpoint, setCheckpoint] = useState('');
  const [country, setCountry] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setNoTruck(false);
    try {
      const w = await queueApi.getWatch();
      setWatch(w);
      // Status needs an assigned truck; a 409 means "no truck" — handled below.
      try {
        setStatus(await queueApi.status());
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) setNoTruck(true);
        else throw e;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t('common.error'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const startWatch = useCallback(async () => {
    if (!checkpoint.trim()) return;
    setBusy(true);
    try {
      const w = await queueApi.setWatch(checkpoint.trim(), country.trim());
      setWatch(w);
      setCheckpoint('');
      setCountry('');
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setBusy(false);
    }
  }, [checkpoint, country, t]);

  const stopWatch = useCallback(async () => {
    setBusy(true);
    try {
      await queueApi.stopWatch();
      setWatch(null);
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setBusy(false);
    }
  }, [t]);

  const refreshNow = useCallback(async () => {
    setBusy(true);
    try {
      const res = await queueApi.refresh();
      setStatus(res.status);
      if (res.status) {
        Alert.alert(t('queue.title'), t(`queue.status.${res.status.status}`));
      }
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setBusy(false);
    }
  }, [t]);

  const book = useCallback(async () => {
    try {
      const { url } = await queueApi.handoff();
      await Linking.openURL(url);
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    }
  }, [t]);

  if (loading) return <Loading />;

  return (
    <Screen
      eyebrow={t('app.name')}
      title={t('queue.title')}
      icon="time"
      refreshing={refreshing}
      onRefresh={() => {
        setRefreshing(true);
        load();
      }}
    >
      {error && <ErrorBox message={error} onRetry={load} retryLabel={t('common.retry')} />}

      {noTruck && (
        <Card>
          <EmptyState icon="bus-outline" title={t('home.noTruck')} />
        </Card>
      )}

      {/* Current status */}
      {!noTruck && (
        <Card>
          <SectionHeader icon="flag" title={t('queue.title')} color={palette.queue} bg={palette.queueBg} />
          {status ? (
            <>
              <Pill
                label={t(`queue.status.${status.status}`)}
                color={STATUS_STYLE[status.status].color}
                bg={STATUS_STYLE[status.status].bg}
              />
              <Row label={t('queue.checkpoint')} value={status.checkpoint} />
              <Row label={t('queue.queueTime')} value={formatDateTime(status.queue_at)} />
              <Row label="Truck" value={status.plate} />
            </>
          ) : (
            <EmptyState icon="flag-outline" title={t('queue.noBooking')} />
          )}
        </Card>
      )}

      {/* Watch control */}
      <Card>
        {watch ? (
          <>
            <View style={styles.watchRow}>
              <IconCircle icon="eye" color={palette.success} bg={palette.successBg} size={38} />
              <View style={styles.watchText}>
                <Text style={styles.watchLabel}>{t('queue.watching')}</Text>
                <Text style={styles.watchValue}>{watch.checkpoint}</Text>
              </View>
              <View style={styles.liveDot} />
            </View>
            {watch.country ? <Row label={t('queue.country')} value={watch.country} /> : null}
            <Button
              label={t('queue.stopWatch')}
              icon="stop-circle-outline"
              variant="danger"
              disabled={busy}
              onPress={stopWatch}
            />
          </>
        ) : (
          <>
            <SectionHeader icon="eye-outline" title={t('queue.startWatch')} color={palette.queue} bg={palette.queueBg} />
            <Field
              label={t('queue.checkpoint')}
              icon="git-merge-outline"
              value={checkpoint}
              onChangeText={setCheckpoint}
              placeholder="Нур Жолы - Хоргос"
            />
            <Field
              label={t('queue.country')}
              icon="flag-outline"
              value={country}
              onChangeText={setCountry}
              placeholder="China"
            />
            <Button
              label={t('queue.startWatch')}
              icon="eye-outline"
              disabled={!checkpoint.trim() || busy}
              onPress={startWatch}
            />
          </>
        )}
      </Card>

      {/* Actions */}
      {!noTruck && (
        <View style={styles.actions}>
          <Button
            label={t('queue.refresh')}
            icon="refresh-outline"
            variant="outline"
            disabled={busy}
            onPress={refreshNow}
            style={styles.actionBtn}
          />
          <Button
            label={t('queue.bookNow')}
            icon="open-outline"
            onPress={book}
            style={styles.actionBtn}
          />
        </View>
      )}

      <Text style={styles.note}>{t('queue.handoffNote')}</Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  watchRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  watchText: { flex: 1, gap: 2 },
  watchLabel: typography.label,
  watchValue: { ...typography.heading, color: palette.ink },
  liveDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: palette.success },
  actions: { flexDirection: 'row', gap: spacing.md },
  actionBtn: { flex: 1 },
  note: { ...typography.caption, lineHeight: 18, paddingHorizontal: spacing.xs },
});
