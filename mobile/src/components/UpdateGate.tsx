import React, { useCallback, useEffect, useState } from 'react';
import { AppState, Linking, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';

import {
  currentVersion,
  fetchDriverVersion,
  isOutdated,
  type DriverVersion,
} from '../lib/app-version';
import { palette, spacing, typography } from '../theme/theme';
import { Button } from './ui';

/**
 * In front of everything else, including sign-in: an app older than the
 * server's minimum shows only how to update. Offline or a failed check lets
 * the app through — a driver must never be locked out by a network blip.
 */
export function UpdateGate({ children }: { children: React.ReactNode }) {
  const [required, setRequired] = useState<DriverVersion | null>(null);

  const check = useCallback(() => {
    fetchDriverVersion()
      .then((v) => setRequired(isOutdated(currentVersion(), v.min_version) ? v : null))
      .catch(() => {});
  }, []);

  useEffect(() => {
    check();
    // Back from the browser with the new APK installed, or a minimum raised
    // while the app sat in the background.
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') check();
    });
    return () => sub.remove();
  }, [check]);

  return required ? <UpdateScreen required={required} /> : <>{children}</>;
}

function UpdateScreen({ required }: { required: DriverVersion }) {
  const { t } = useTranslation();
  return (
    <View style={styles.screen}>
      <Ionicons name="cloud-download-outline" size={56} color={palette.brand} />
      <Text style={styles.title}>{t('update.title')}</Text>
      <Text style={styles.body}>{t('update.body')}</Text>
      <Text style={styles.versions}>
        {t('update.versions', { current: currentVersion() ?? '?', required: required.min_version })}
      </Text>
      {required.download_url ? (
        <Button
          label={t('update.download')}
          icon="download-outline"
          onPress={() => Linking.openURL(required.download_url)}
        />
      ) : (
        <Text style={styles.body}>{t('update.askDispatcher')}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
    padding: spacing.xl,
    backgroundColor: palette.background,
  },
  title: { ...typography.heading, color: palette.ink, textAlign: 'center' },
  body: { ...typography.body, color: palette.inkSoft, textAlign: 'center' },
  versions: { ...typography.caption, color: palette.muted },
});
