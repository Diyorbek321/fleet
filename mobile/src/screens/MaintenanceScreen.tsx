import React, { useCallback, useEffect, useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';

import { meApi, type MaintenanceRecord } from '../lib/me';
import { formatDate } from '../lib/format';
import { haptics } from '../lib/haptics';
import { palette, radius, spacing, typography } from '../theme/theme';
import { Screen } from '../components/Screen';
import {
  Button,
  Card,
  EmptyState,
  Field,
  Loading,
  SectionHeader,
} from '../components/ui';

export function MaintenanceScreen() {
  const { t } = useTranslation();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [records, setRecords] = useState<MaintenanceRecord[]>([]);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRecords(await meApi.maintenance());
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

  const submit = useCallback(async () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      await meApi.reportIssue({ title: title.trim(), description: description.trim() || null });
      setTitle('');
      setDescription('');
      haptics.success();
      Alert.alert(t('maintenance.submitted'));
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setBusy(false);
    }
  }, [title, description, busy, t]);

  if (loading) return <Loading />;

  return (
    <Screen
      eyebrow={t('app.name')}
      title={t('maintenance.title')}
      icon="construct"
      refreshing={refreshing}
      onRefresh={() => {
        setRefreshing(true);
        load();
      }}
    >
      <Card>
        <SectionHeader
          icon="warning"
          title={t('maintenance.reportIssue')}
          color={palette.maintenance}
          bg={palette.maintenanceBg}
        />
        <Field label={t('maintenance.issueTitle')} icon="alert-circle-outline" value={title} onChangeText={setTitle} placeholder="—" />
        <Field
          label={t('maintenance.issueDescription')}
          value={description}
          onChangeText={setDescription}
          placeholder="—"
          multiline
          style={styles.multiline}
        />
        <Button label={t('maintenance.submit')} icon="send-outline" onPress={submit} disabled={!title.trim()} loading={busy} />
      </Card>

      <Card>
        <SectionHeader
          icon="time"
          title={t('maintenance.history')}
          color={palette.maintenance}
          bg={palette.maintenanceBg}
        />
        {records.length === 0 ? (
          <EmptyState icon="construct-outline" title={t('maintenance.empty')} />
        ) : (
          records.map((r) => (
            <View key={r.id} style={styles.item}>
              <View style={styles.itemIcon}>
                <Ionicons name="build" size={18} color={palette.maintenance} />
              </View>
              <View style={styles.itemBody}>
                <Text style={styles.itemTitle}>{r.service_type}</Text>
                {r.description ? <Text style={styles.desc}>{r.description}</Text> : null}
              </View>
              <Text style={styles.date}>{formatDate(r.performed_at)}</Text>
            </View>
          ))
        )}
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  multiline: { minHeight: 88, textAlignVertical: 'top', paddingTop: 12 },
  item: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
    borderTopWidth: 1,
    borderTopColor: palette.line,
    paddingTop: spacing.md,
  },
  itemIcon: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    backgroundColor: palette.maintenanceBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  itemBody: { flex: 1, gap: 2 },
  itemTitle: { ...typography.body, color: palette.ink, fontWeight: '700' },
  desc: typography.caption,
  date: { ...typography.caption, color: palette.muted },
});
