import React, { useCallback, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';

import { ApiError } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { palette, radius, shadow, spacing, typography } from '../theme/theme';
import { Button, Field } from '../components/ui';
import { LanguageSwitcher } from '../components/LanguageSwitcher';

export function LoginScreen() {
  const { t } = useTranslation();
  const { signIn } = useAuth();
  const insets = useSafeAreaInsets();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = email.trim().length > 0 && password.length > 0 && !submitting;

  const onSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 0) setError(t('auth.backendUnreachable'));
        else if (e.status === 401) setError(t('auth.invalidCredentials'));
        else setError(t('auth.loginFailed'));
      } else {
        setError(t('auth.loginFailed'));
      }
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, email, password, signIn, t]);

  return (
    <LinearGradient colors={palette.gradientNavy} style={styles.screen}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={[
            styles.content,
            { paddingTop: insets.top + spacing.xxl, paddingBottom: insets.bottom + spacing.xl },
          ]}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.brand}>
            <View style={styles.logo}>
              <Ionicons name="bus" size={30} color={palette.white} />
            </View>
            <Text style={styles.appName}>{t('app.name')}</Text>
            <Text style={styles.heading}>{t('auth.heading')}</Text>
            <Text style={styles.subtitle}>{t('auth.subtitle')}</Text>
          </View>

          <View style={styles.form}>
            <Field
              label={t('auth.email')}
              icon="mail-outline"
              value={email}
              onChangeText={setEmail}
              placeholder={t('auth.emailPlaceholder')}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              textContentType="emailAddress"
              editable={!submitting}
            />
            <Field
              label={t('auth.password')}
              icon="lock-closed-outline"
              value={password}
              onChangeText={setPassword}
              placeholder={t('auth.passwordPlaceholder')}
              secureTextEntry
              textContentType="password"
              editable={!submitting}
              onSubmitEditing={onSubmit}
              returnKeyType="go"
            />

            {error && (
              <View style={styles.errorRow}>
                <Ionicons name="alert-circle" size={16} color={palette.danger} />
                <Text style={styles.error}>{error}</Text>
              </View>
            )}

            <Button
              label={t('auth.signIn')}
              icon="log-in-outline"
              onPress={onSubmit}
              disabled={!canSubmit}
              loading={submitting}
            />
          </View>

          <View style={styles.footer}>
            <LanguageSwitcher />
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  flex: { flex: 1 },
  content: { paddingHorizontal: spacing.xxl, gap: spacing.xxl, flexGrow: 1, justifyContent: 'center' },
  brand: { gap: 6, alignItems: 'flex-start' },
  logo: {
    width: 60,
    height: 60,
    borderRadius: radius.lg,
    backgroundColor: palette.brand,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
    ...shadow.lg,
  },
  appName: { color: '#93c5fd', fontSize: 13, fontWeight: '700', letterSpacing: 1.5 },
  heading: { ...typography.display, color: palette.white },
  subtitle: { color: '#94a3b8', fontSize: 15 },
  form: {
    backgroundColor: palette.white,
    borderRadius: radius.xl,
    padding: spacing.xl,
    gap: spacing.md,
    ...shadow.lg,
  },
  errorRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  error: { color: palette.danger, fontSize: 14, fontWeight: '600', flex: 1 },
  footer: { alignItems: 'center' },
});
