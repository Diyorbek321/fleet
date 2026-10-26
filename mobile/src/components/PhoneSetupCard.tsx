import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import {
  markPhoneSetupDone,
  needsAutostart,
  needsPhoneSetup,
  openAutostartSettings,
  openBatterySettings,
  phoneManufacturer,
} from '../lib/phone-setup';
import { palette, spacing, typography } from '../theme/theme';
import { Button, Card, SectionHeader } from './ui';

/**
 * A one-time walk through the phone settings that stop tracking with the app
 * closed: battery optimisation, and the maker's autostart list where there is
 * one. Shown until the driver confirms; Android only.
 */
export function PhoneSetupCard() {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);
  const autostart = needsAutostart(phoneManufacturer());

  useEffect(() => {
    needsPhoneSetup().then(setVisible);
  }, []);

  if (!visible) return null;

  return (
    <Card style={styles.card}>
      <SectionHeader
        icon="battery-charging"
        title={t('phoneSetup.title')}
        color={palette.warning}
        bg={palette.warningBg}
      />
      <Text style={typography.body}>{t('phoneSetup.body')}</Text>

      <View style={styles.step}>
        <Text style={styles.stepText}>{t('phoneSetup.batteryStep')}</Text>
        <Button
          label={t('phoneSetup.batteryButton')}
          icon="battery-full-outline"
          variant="ghost"
          onPress={openBatterySettings}
        />
      </View>

      {autostart ? (
        <View style={styles.step}>
          <Text style={styles.stepText}>{t('phoneSetup.autostartStep')}</Text>
          <Button
            label={t('phoneSetup.autostartButton')}
            icon="rocket-outline"
            variant="ghost"
            onPress={openAutostartSettings}
          />
        </View>
      ) : null}

      <Button
        label={t('phoneSetup.done')}
        icon="checkmark-circle-outline"
        onPress={() => {
          setVisible(false);
          void markPhoneSetupDone();
        }}
      />
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderColor: palette.warning, gap: spacing.md },
  step: { gap: spacing.xs },
  stepText: { ...typography.caption, color: palette.inkSoft },
});
