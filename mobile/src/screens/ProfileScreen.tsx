import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { meApi, type DriverProfile, type SafetyScore } from '../lib/me';
import { formatDate } from '../lib/format';
import { useAuth } from '../contexts/AuthContext';
import { palette, radius, spacing, typography } from '../theme/theme';
import { LanguageSwitcher } from '../components/LanguageSwitcher';
import { Screen } from '../components/Screen';
import {
  Button,
  Card,
  ErrorBox,
  EmptyState,
  Loading,
  Row,
  SectionHeader,
  StatTile,
} from '../components/ui';

/** Color the safety score by band so drivers read it at a glance. */
function scoreColor(score: number): { color: string; bg: string } {
  if (score >= 80) return { color: palette.safety, bg: palette.safetyBg };
  if (score >= 60) return { color: palette.warning, bg: palette.warningBg };
  return { color: palette.danger, bg: palette.dangerBg };
}

function initials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('');
}

export function ProfileScreen() {
  const { t } = useTranslation();
  const { signOut } = useAuth();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState<DriverProfile | null>(null);
  const [safety, setSafety] = useState<SafetyScore | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, s] = await Promise.all([meApi.profile(), meApi.safetyScore()]);
      setProfile(p);
      setSafety(s);
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

  if (loading) return <Loading />;

  const band = safety ? scoreColor(safety.score) : null;

  return (
    <Screen
      eyebrow={t('app.name')}
      title={t('profile.title')}
      icon="person-circle"
      refreshing={refreshing}
      onRefresh={() => {
        setRefreshing(true);
        load();
      }}
    >
      {error && <ErrorBox message={error} onRetry={load} retryLabel={t('common.retry')} />}

      {profile && (
        <Card>
          <View style={styles.identity}>
            <View style={styles.avatar}>
              <Text style={styles.avatarText}>{initials(profile.name)}</Text>
            </View>
            <View style={styles.identityText}>
              <Text style={styles.name}>{profile.name}</Text>
              {profile.phone ? <Text style={styles.phone}>{profile.phone}</Text> : null}
            </View>
          </View>
          <Row label={t('profile.license')} value={profile.license_number} />
          <Row label={t('profile.licenseExpiry')} value={formatDate(profile.license_expiry)} />
        </Card>
      )}

      <Card>
        <SectionHeader
          icon="shield-checkmark"
          title={t('safety.title')}
          color={band?.color ?? palette.safety}
          bg={band?.bg ?? palette.safetyBg}
          right={
            safety ? (
              <Text style={[styles.bigScore, { color: band?.color }]}>{safety.score}</Text>
            ) : undefined
          }
        />
        {safety ? (
          <>
            <View style={styles.statRow}>
              <StatTile
                icon="speedometer-outline"
                value={`${safety.speeding_events}`}
                label={t('safety.speeding')}
                color={palette.danger}
                bg={palette.dangerBg}
              />
              <StatTile
                icon="hand-left-outline"
                value={`${safety.harsh_braking}`}
                label={t('safety.harshBraking')}
                color={palette.warning}
                bg={palette.warningBg}
              />
            </View>
            <View style={styles.statRow}>
              <StatTile
                icon="trending-up-outline"
                value={`${safety.harsh_acceleration}`}
                label={t('safety.harshAccel')}
                color={palette.warning}
                bg={palette.warningBg}
              />
              <StatTile
                icon="pause-outline"
                value={`${safety.idle_time_minutes}`}
                label={t('safety.idleTime')}
                color={palette.mileage}
                bg={palette.mileageBg}
              />
            </View>
          </>
        ) : (
          <EmptyState icon="shield-outline" title={t('safety.noData')} />
        )}
      </Card>

      <Card>
        <LanguageSwitcher />
      </Card>

      <Button label={t('profile.logout')} icon="log-out-outline" variant="danger" onPress={signOut} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  identity: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg },
  avatar: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: palette.brand,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { color: palette.white, fontSize: 22, fontWeight: '800' },
  identityText: { flex: 1, gap: 2 },
  name: typography.title,
  phone: { ...typography.body, color: palette.muted },
  bigScore: { fontSize: 26, fontWeight: '800' },
  statRow: { flexDirection: 'row', gap: spacing.md },
});
