import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import type { DriverMessage } from '../lib/me';
import { formatDateTime } from '../lib/format';
import { palette, spacing, typography } from '../theme/theme';
import { Card, EmptyState, Pill, SectionHeader } from './ui';

/** How many messages the home screen shows before "show all". */
const COLLAPSED_COUNT = 3;

/**
 * The driver's inbox: what the dispatcher sent, and the GPS warnings.
 *
 * Tapping an unread message marks it read — that is what the dispatcher sees
 * as "O'qildi" in the panel, so it only happens on a deliberate tap, never on
 * merely scrolling past.
 */
export function MessagesCard({
  messages,
  onRead,
}: {
  messages: DriverMessage[];
  onRead: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const unread = messages.filter((m) => !m.read_at).length;
  const shown = expanded ? messages : messages.slice(0, COLLAPSED_COUNT);

  return (
    <Card>
      <SectionHeader
        icon="chatbubbles"
        title={t('messages.title')}
        color={unread ? palette.danger : palette.brand}
        bg={unread ? palette.dangerBg : palette.brandLight}
        right={
          unread ? (
            <Pill
              label={t('messages.unread', { count: unread })}
              color={palette.danger}
              bg={palette.dangerBg}
            />
          ) : undefined
        }
      />
      {messages.length === 0 ? (
        <EmptyState icon="chatbubbles-outline" title={t('messages.empty')} />
      ) : (
        <>
          {shown.map((m) => (
            <Pressable
              key={m.id}
              accessibilityRole="button"
              onPress={() => (m.read_at ? undefined : onRead(m.id))}
              style={[styles.item, !m.read_at && styles.unreadItem]}
            >
              <View style={styles.itemHead}>
                {!m.read_at && <View style={styles.dot} />}
                <Text style={styles.itemTitle} numberOfLines={1}>
                  {m.title}
                </Text>
              </View>
              <Text style={typography.body}>{m.body}</Text>
              <Text style={typography.caption}>{formatDateTime(m.created_at)}</Text>
            </Pressable>
          ))}
          {messages.length > COLLAPSED_COUNT && (
            <Pressable accessibilityRole="button" onPress={() => setExpanded((v) => !v)}>
              <Text style={styles.more}>
                {expanded ? t('messages.showLess') : t('messages.showAll')}
              </Text>
            </Pressable>
          )}
        </>
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  item: { gap: 4, paddingVertical: spacing.sm, paddingHorizontal: spacing.sm, borderRadius: 10 },
  unreadItem: { backgroundColor: palette.brandLight },
  itemHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: palette.danger },
  itemTitle: { ...typography.heading, flex: 1 },
  more: { ...typography.label, color: palette.brand, textAlign: 'center', paddingTop: spacing.sm },
});
