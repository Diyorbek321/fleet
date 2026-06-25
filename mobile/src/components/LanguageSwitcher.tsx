import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES, setLanguage, type LanguageCode } from '../i18n';

/**
 * A row of language chips (English / O‘zbekcha / Русский). Tapping one switches
 * the app language immediately and persists the choice across launches.
 */
export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const current = i18n.language as LanguageCode;

  return (
    <View style={styles.container}>
      <Text style={styles.label}>{t('language.title')}</Text>
      <View style={styles.row}>
        {SUPPORTED_LANGUAGES.map((lang) => {
          const active = current === lang.code;
          return (
            <Pressable
              key={lang.code}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => setLanguage(lang.code)}
              style={[styles.chip, active && styles.chipActive]}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {lang.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 8 },
  label: { fontSize: 13, fontWeight: '600', color: '#64748b' },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: '#e2e8f0',
    backgroundColor: '#f1f5f9',
  },
  chipActive: { backgroundColor: '#2563eb', borderColor: '#2563eb' },
  chipText: { fontSize: 14, fontWeight: '600', color: '#334155' },
  chipTextActive: { color: '#fff', fontWeight: '700' },
});
