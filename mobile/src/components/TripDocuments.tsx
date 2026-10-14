import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';

import { meApi, type TripDocument, type TripDocumentCategory } from '../lib/me';
import { pickPhoto } from '../lib/pickPhoto';
import { palette, radius, spacing, typography } from '../theme/theme';
import { haptics } from '../lib/haptics';
import { Button, EmptyState, Loading } from './ui';
import { DOC_CATEGORIES as CATEGORIES, TripDocumentSheet } from './TripDocumentSheet';

/**
 * Per-trip document panel: pick a category, capture/select a photo, upload it,
 * and show the trip's existing documents as a thumbnail grid. Scoped to a single
 * `tripId` so trips never share state. Tapping a photo opens it to relabel,
 * retake or delete — until the trip is closed (`locked`). Uploading stays open
 * after delivery: the signed CMR comes back after unloading.
 */
export function TripDocuments({ tripId, locked = false }: { tripId: string; locked?: boolean }) {
  const { t } = useTranslation();

  const [docs, setDocs] = useState<TripDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [category, setCategory] = useState<TripDocumentCategory>('cmr');
  const [opened, setOpened] = useState<TripDocument | null>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await meApi.listTripDocuments(tripId));
    } catch (e) {
      Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
    } finally {
      setLoading(false);
    }
  }, [tripId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const pickFrom = useCallback(
    async (source: 'camera' | 'library') => {
      const asset = await pickPhoto(source, t);
      if (!asset) return;

      setBusy(true);
      try {
        await meApi.uploadTripDocument(tripId, asset, { category });
        void haptics.success();
        Alert.alert(t('tripDocs.uploaded'));
        await load();
      } catch (e) {
        void haptics.error();
        Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
      } finally {
        setBusy(false);
      }
    },
    [tripId, category, load, t],
  );

  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>{t('tripDocs.category')}</Text>
      <View style={styles.catRow}>
        {CATEGORIES.map((c) => {
          const active = c === category;
          return (
            <Pressable
              key={c}
              onPress={() => setCategory(c)}
              style={[styles.catChip, active && styles.catChipActive]}
            >
              <Text style={[styles.catChipText, active && styles.catChipTextActive]}>
                {t(`tripDocs.cat.${c}`)}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.actions}>
        <Button
          label={t('tripDocs.camera')}
          icon="camera-outline"
          onPress={() => pickFrom('camera')}
          loading={busy}
          style={styles.actionBtn}
        />
        <Button
          label={t('tripDocs.gallery')}
          icon="images-outline"
          variant="outline"
          onPress={() => pickFrom('library')}
          disabled={busy}
          style={styles.actionBtn}
        />
      </View>

      {loading ? (
        <Loading />
      ) : docs.length === 0 ? (
        <EmptyState icon="document-outline" title={t('tripDocs.empty')} />
      ) : (
        <View style={styles.grid}>
          {!locked && <Text style={styles.hint}>{t('tripDocs.tapHint')}</Text>}
          {docs.map((doc) => (
            <Pressable key={doc.id} style={styles.thumbWrap} onPress={() => setOpened(doc)}>
              <Image source={{ uri: doc.url }} style={styles.thumb} resizeMode="cover" />
              {doc.category ? (
                <View style={styles.thumbTag}>
                  <Ionicons name="pricetag" size={10} color={palette.white} />
                  <Text style={styles.thumbTagText} numberOfLines={1}>
                    {doc.category}
                  </Text>
                </View>
              ) : null}
            </Pressable>
          ))}
        </View>
      )}

      <TripDocumentSheet
        tripId={tripId}
        doc={opened}
        locked={locked}
        onClose={() => setOpened(null)}
        onChanged={load}
      />
    </View>
  );
}

const THUMB = 92;

const styles = StyleSheet.create({
  wrap: {
    gap: spacing.md,
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: palette.line,
  },
  label: typography.label,
  catRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  catChip: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
    backgroundColor: palette.brandLight,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  catChipActive: { backgroundColor: palette.brand, borderColor: palette.brand },
  catChipText: { ...typography.label, color: palette.brand },
  catChipTextActive: { color: palette.white },
  actions: { flexDirection: 'row', gap: spacing.sm },
  actionBtn: { flex: 1 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  hint: { ...typography.caption, width: '100%' },
  thumbWrap: {
    width: THUMB,
    height: THUMB,
    borderRadius: radius.md,
    overflow: 'hidden',
    backgroundColor: palette.surfaceAlt,
  },
  thumb: { width: '100%', height: '100%' },
  thumbTag: {
    position: 'absolute',
    left: 4,
    bottom: 4,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    maxWidth: THUMB - 8,
    paddingVertical: 2,
    paddingHorizontal: 6,
    borderRadius: radius.pill,
    backgroundColor: 'rgba(15,23,42,0.7)',
  },
  thumbTagText: { color: palette.white, fontSize: 10, fontWeight: '700' },
});
