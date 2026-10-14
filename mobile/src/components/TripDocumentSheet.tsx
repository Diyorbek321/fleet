import React, { useEffect, useState } from 'react';
import {
  Alert,
  Image,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';

import { meApi, type TripDocument, type TripDocumentCategory } from '../lib/me';
import { pickPhoto } from '../lib/pickPhoto';
import { haptics } from '../lib/haptics';
import { palette, radius, spacing, typography } from '../theme/theme';
import { Button, Field } from './ui';

export const DOC_CATEGORIES: TripDocumentCategory[] = ['cmr', 'invoice', 'customs', 'other'];

interface Props {
  tripId: string;
  doc: TripDocument | null;
  /** The trip is delivered or cancelled: look, but no changes. */
  locked: boolean;
  onClose: () => void;
  /** Called after any change, so the list reloads. */
  onChanged: () => void;
}

/**
 * One document photo, opened from the trip's grid: see it large, relabel it,
 * retake it, or delete it. While the trip is still running only — after that
 * the desk owns the paperwork.
 */
export function TripDocumentSheet({ tripId, doc, locked, onClose, onChanged }: Props) {
  const { t } = useTranslation();
  const [category, setCategory] = useState<string | null>(null);
  const [caption, setCaption] = useState('');
  const [busy, setBusy] = useState<'save' | 'retake' | 'delete' | null>(null);

  useEffect(() => {
    setCategory(doc?.category ?? null);
    setCaption(doc?.caption ?? '');
  }, [doc]);

  if (!doc) return null;

  const fail = (e: unknown) => {
    void haptics.error();
    Alert.alert(t('common.error'), e instanceof Error ? e.message : '');
  };

  const run = async (kind: 'save' | 'retake' | 'delete', action: () => Promise<boolean>) => {
    setBusy(kind);
    try {
      if (await action()) {
        void haptics.success();
        onChanged();
        onClose();
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  const save = () =>
    run('save', async () => {
      await meApi.updateTripDocument(tripId, doc.id, {
        category,
        caption: caption.trim() || null,
      });
      return true;
    });

  const retake = (source: 'camera' | 'library') =>
    run('retake', async () => {
      const asset = await pickPhoto(source, t);
      if (!asset) return false;
      await meApi.replaceTripDocumentFile(tripId, doc.id, asset);
      return true;
    });

  const confirmDelete = () =>
    Alert.alert(t('tripDocs.deleteTitle'), t('tripDocs.deleteBody'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('tripDocs.delete'),
        style: 'destructive',
        onPress: () =>
          run('delete', async () => {
            await meApi.deleteTripDocument(tripId, doc.id);
            return true;
          }),
      },
    ]);

  const dirty = category !== (doc.category ?? null) || caption.trim() !== (doc.caption ?? '');

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.backdrop}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={typography.heading}>{t('tripDocs.document')}</Text>
            <Pressable onPress={onClose} hitSlop={12}>
              <Ionicons name="close" size={24} color={palette.muted} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            <Image source={{ uri: doc.url }} style={styles.preview} resizeMode="contain" />

            {locked ? (
              <View style={styles.lockNote}>
                <Ionicons name="lock-closed" size={16} color={palette.muted} />
                <Text style={styles.lockText}>{t('tripDocs.locked')}</Text>
              </View>
            ) : (
              <>
                <Text style={styles.label}>{t('tripDocs.category')}</Text>
                <View style={styles.catRow}>
                  {DOC_CATEGORIES.map((c) => {
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
                <Field
                  label={t('tripDocs.note')}
                  value={caption}
                  onChangeText={setCaption}
                  maxLength={2000}
                  placeholder={t('tripDocs.notePlaceholder')}
                />
                <Button
                  label={t('common.save')}
                  icon="checkmark"
                  onPress={save}
                  loading={busy === 'save'}
                  disabled={!dirty || busy !== null}
                />
                <View style={styles.row}>
                  <Button
                    label={t('tripDocs.retake')}
                    icon="camera-outline"
                    variant="outline"
                    onPress={() => retake('camera')}
                    loading={busy === 'retake'}
                    disabled={busy !== null}
                    style={styles.flex}
                  />
                  <Button
                    label={t('tripDocs.gallery')}
                    icon="images-outline"
                    variant="outline"
                    onPress={() => retake('library')}
                    disabled={busy !== null}
                    style={styles.flex}
                  />
                </View>
                <Button
                  label={t('tripDocs.delete')}
                  icon="trash-outline"
                  variant="danger"
                  onPress={confirmDelete}
                  loading={busy === 'delete'}
                  disabled={busy !== null}
                />
              </>
            )}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(15,23,42,0.5)' },
  sheet: {
    maxHeight: '92%',
    backgroundColor: palette.white,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: palette.line,
  },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl },
  preview: {
    width: '100%',
    height: 300,
    borderRadius: radius.md,
    backgroundColor: palette.surfaceAlt,
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
  row: { flexDirection: 'row', gap: spacing.sm },
  flex: { flex: 1 },
  lockNote: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: palette.surfaceAlt,
  },
  lockText: { ...typography.body, color: palette.muted, flex: 1 },
});
