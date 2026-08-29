import React, { useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { changePassword } from '../lib/authApi';
import { palette, radius, spacing, typography } from '../theme/theme';
import { Button, Card, Field, SectionHeader } from './ui';

interface Props {
  /**
   * The account is on a password a dispatcher chose and still knows.
   *
   * Opens the form and explains why, rather than leaving the driver to find a
   * collapsed section on their own. Deliberately not a hard block: a driver
   * mid-run needs their trip screen more than the platform needs this done in
   * the next thirty seconds, and locking them out of the app to enforce it
   * would cost more than the flag is worth.
   */
  required?: boolean;
}

export function ChangePassword({ required = false }: Props) {
  const { t } = useTranslation();

  const [open, setOpen] = useState(required);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (next !== confirm) {
      setError(t('password.doNotMatch'));
      return;
    }
    if (next.length < 8) {
      setError(t('password.tooShort'));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await changePassword(current, next);
      setCurrent('');
      setNext('');
      setConfirm('');
      setOpen(false);
      Alert.alert(t('password.changed'), t('password.otherDevicesSignedOut'));
    } catch (e) {
      setError(e instanceof Error ? e.message : t('common.error'));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <Card>
        <SectionHeader icon="key-outline" title={t('password.title')} />
        <Button
          label={t('password.change')}
          variant="outline"
          icon="key-outline"
          onPress={() => setOpen(true)}
        />
      </Card>
    );
  }

  return (
    <Card>
      <SectionHeader icon="key-outline" title={t('password.title')} />

      {required && (
        <View style={styles.notice}>
          <Text style={styles.noticeText}>{t('password.setByAdmin')}</Text>
        </View>
      )}

      <View style={styles.form}>
        <Field
          label={t('password.current')}
          icon="lock-closed-outline"
          secureTextEntry
          autoCapitalize="none"
          value={current}
          onChangeText={setCurrent}
        />
        <Field
          label={t('password.new')}
          icon="key-outline"
          secureTextEntry
          autoCapitalize="none"
          value={next}
          onChangeText={setNext}
        />
        <Field
          label={t('password.confirm')}
          icon="key-outline"
          secureTextEntry
          autoCapitalize="none"
          value={confirm}
          onChangeText={setConfirm}
        />

        {error && <Text style={styles.error}>{error}</Text>}

        <View style={styles.actions}>
          {!required && (
            <Button
              label={t('common.cancel')}
              variant="ghost"
              style={styles.action}
              onPress={() => {
                setOpen(false);
                setError(null);
              }}
            />
          )}
          <Button
            label={t('password.save')}
            style={styles.action}
            loading={saving}
            disabled={saving}
            onPress={submit}
          />
        </View>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  form: { gap: spacing.md },
  actions: { flexDirection: 'row', gap: spacing.sm },
  action: { flex: 1 },
  error: { ...typography.body, color: palette.danger },
  notice: {
    backgroundColor: palette.warningBg,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  noticeText: { ...typography.body, color: palette.warning },
});
