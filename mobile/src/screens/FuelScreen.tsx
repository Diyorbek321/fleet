import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';

import { ApiError } from '../lib/api';
import { meApi, type FuelLog } from '../lib/me';
import { formatDateTime } from '../lib/format';
import { palette, radius, spacing, typography } from '../theme/theme';
import { Screen } from '../components/Screen';
import {
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Loading,
  SectionHeader,
} from '../components/ui';

export function FuelScreen() {
  const { t } = useTranslation();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [noTruck, setNoTruck] = useState(false);
  const [logs, setLogs] = useState<FuelLog[]>([]);

  const [liters, setLiters] = useState('');
  const [price, setPrice] = useState('');
  const [station, setStation] = useState('');
  const [odometer, setOdometer] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setNoTruck(false);
    try {
      setLogs(await meApi.fuelLogs());
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const totalSpent = useMemo(
    () => logs.reduce((sum, log) => sum + Number(log.total_cost ?? 0), 0),
    [logs],
  );

  const canSubmit = Number(liters) > 0 && Number(price) > 0 && !busy;

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      await meApi.addFuelLog({
        liters: Number(liters),
        cost_per_liter: Number(price),
        mileage_at_fill: odometer.trim() ? Number(odometer) : null,
        fuel_station: station.trim() || null,
      });
      setLiters('');
      setPrice('');
      setStation('');
      setOdometer('');
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setNoTruck(true);
      else Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setBusy(false);
    }
  }, [canSubmit, liters, price, station, odometer, load, t]);

  if (loading) return <Loading />;

  return (
    <Screen
      eyebrow={t('app.name')}
      title={t('fuel.title')}
      subtitle={
        logs.length
          ? `${t('fuel.total')}: ${totalSpent.toLocaleString()} · ${logs.length}`
          : undefined
      }
      icon="speedometer"
      refreshing={refreshing}
      onRefresh={() => {
        setRefreshing(true);
        load();
      }}
    >
      {noTruck && <ErrorBox message={t('home.noTruck')} />}

      <Card>
        <SectionHeader
          icon="add-circle"
          title={t('fuel.addLog')}
          color={palette.fuel}
          bg={palette.fuelBg}
        />
        <View style={styles.pair}>
          <View style={styles.pairItem}>
            <Field label={t('fuel.liters')} icon="water-outline" value={liters} onChangeText={setLiters} keyboardType="numeric" placeholder="0" />
          </View>
          <View style={styles.pairItem}>
            <Field label={t('fuel.costPerLiter')} icon="cash-outline" value={price} onChangeText={setPrice} keyboardType="numeric" placeholder="0" />
          </View>
        </View>
        <Field label={t('fuel.odometer')} icon="navigate-outline" value={odometer} onChangeText={setOdometer} keyboardType="numeric" placeholder="0" />
        <Field label={t('fuel.station')} icon="location-outline" value={station} onChangeText={setStation} placeholder="—" />
        <Button label={t('fuel.save')} icon="save-outline" onPress={submit} disabled={!canSubmit} loading={busy} />
      </Card>

      <Card>
        <SectionHeader
          icon="time"
          title={t('fuel.title')}
          color={palette.fuel}
          bg={palette.fuelBg}
        />
        {logs.length === 0 ? (
          <EmptyState icon="speedometer-outline" title={t('fuel.empty')} />
        ) : (
          logs.map((log) => (
            <View key={log.id} style={styles.logItem}>
              <View style={styles.logIcon}>
                <Ionicons name="water" size={18} color={palette.fuel} />
              </View>
              <View style={styles.logBody}>
                <Text style={styles.logTitle}>
                  {log.liters} {t('common.litersShort')}
                </Text>
                <Text style={styles.logMeta}>
                  {formatDateTime(log.filled_at)}
                  {log.fuel_station ? ` · ${log.fuel_station}` : ''}
                </Text>
              </View>
              <Text style={styles.logCost}>{Number(log.total_cost).toLocaleString()}</Text>
            </View>
          ))
        )}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  pair: { flexDirection: 'row', gap: spacing.md },
  pairItem: { flex: 1 },
  logItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderTopWidth: 1,
    borderTopColor: palette.line,
    paddingTop: spacing.md,
  },
  logIcon: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    backgroundColor: palette.fuelBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logBody: { flex: 1, gap: 2 },
  logTitle: { ...typography.body, color: palette.ink, fontWeight: '700' },
  logMeta: typography.caption,
  logCost: { ...typography.heading, color: palette.ink },
});
