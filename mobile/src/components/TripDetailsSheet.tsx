import React from 'react';
import { Linking, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { mapsUrl, tripDetailSections, type DetailRow } from '../lib/tripDetails';
import type { Trip } from '../lib/trips';
import { palette, radius, spacing, typography } from '../theme/theme';
import { Card } from './ui';

interface Props {
  trip: Trip;
  onClose: () => void;
}

/**
 * Everything the dispatcher entered for one trip, on its own screen: the
 * customer, both addresses, the contacts (tap to call), customs and dates.
 */
export function TripDetailsSheet({ trip, onClose }: Props) {
  const { t } = useTranslation();
  const insets = useSafeAreaInsets();
  const sections = tripDetailSections(trip, t);

  return (
    <Modal visible animationType="slide" presentationStyle="fullScreen" onRequestClose={onClose}>
      <View style={[styles.screen, { paddingTop: insets.top }]}>
        <View style={styles.header}>
          <View style={styles.headerText}>
            <Text style={styles.eyebrow}>{t('tripDetails.title')}</Text>
            <Text style={styles.reference}>{trip.reference}</Text>
          </View>
          <Pressable
            onPress={onClose}
            accessibilityRole="button"
            accessibilityLabel={t('tripDetails.close')}
            hitSlop={12}
            style={styles.close}
          >
            <Ionicons name="close" size={24} color={palette.ink} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={[styles.body, { paddingBottom: insets.bottom + spacing.xl }]}>
          {sections.map((section) => (
            <Card key={section.key}>
              <Text style={styles.sectionTitle}>{t(`tripDetails.section.${section.key}`)}</Text>
              {section.rows.map((row) => (
                <DetailLine key={row.key} row={row} />
              ))}
            </Card>
          ))}
        </ScrollView>
      </View>
    </Modal>
  );
}

function DetailLine({ row }: { row: DetailRow }) {
  const { t } = useTranslation();
  return (
    <View style={styles.line}>
      <Text style={styles.label}>{t(`tripDetails.field.${row.key}`)}</Text>
      <Text style={styles.value} selectable>
        {row.value}
      </Text>
      {row.phone ? (
        <Pressable
          onPress={() => Linking.openURL(`tel:${row.phone}`)}
          accessibilityRole="button"
          style={styles.call}
        >
          <Ionicons name="call" size={16} color={palette.brand} />
          <Text style={styles.callText}>{t('tripDetails.call')}</Text>
        </Pressable>
      ) : null}
      {row.navigable ? (
        <Pressable
          onPress={() => Linking.openURL(mapsUrl(row.value, Platform.OS)).catch(() => {})}
          accessibilityRole="button"
          style={styles.call}
        >
          <Ionicons name="navigate" size={16} color={palette.brand} />
          <Text style={styles.callText}>{t('tripDetails.navigate')}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.background },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: palette.line,
  },
  headerText: { flex: 1 },
  eyebrow: { ...typography.caption, color: palette.muted },
  reference: { ...typography.heading, color: palette.ink },
  close: { padding: spacing.xs },
  body: { padding: spacing.lg, gap: spacing.md },
  sectionTitle: { ...typography.label, color: palette.muted, marginBottom: spacing.sm },
  line: { paddingVertical: spacing.xs },
  label: { ...typography.caption, color: palette.muted },
  value: { ...typography.body, color: palette.ink },
  call: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    alignSelf: 'flex-start',
    marginTop: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: radius.md,
    backgroundColor: palette.brandLight,
  },
  callText: { ...typography.label, color: palette.brand },
});
