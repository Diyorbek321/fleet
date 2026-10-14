import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { meApi } from '../lib/me';
import { dmy, stayLevel, type StayLevel, type StaySummary } from '../lib/russiaStay';
import { palette, spacing, typography } from '../theme/theme';
import { Card, SectionHeader } from './ui';

const LEVEL_COLORS: Record<StayLevel, { color: string; bg: string }> = {
  ok: { color: palette.info, bg: palette.infoBg },
  soon: { color: palette.warning, bg: palette.warningBg },
  urgent: { color: palette.danger, bg: palette.dangerBg },
  over: { color: palette.danger, bg: palette.dangerBg },
};

/**
 * The driver's days in Russia: which day of the stay it is and the last day
 * they may be there (90 in any 180). Hidden when Russia does not concern them
 * — no stay inside the last 180 days. Loads on its own, so a failure here
 * never blocks the shift controls; `refreshKey` reloads it with the screen.
 */
export function RussiaStayCard({ refreshKey }: { refreshKey: number }) {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<StaySummary | null>(null);

  useEffect(() => {
    // A slower, older answer must not overwrite a newer one, nor land after unmount.
    let current = true;
    meApi
      .russiaStay()
      .then((s) => current && setSummary(s))
      // Kept quiet on purpose: the card keeps its last value rather than put
      // an error dialog in front of the shift controls.
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [refreshKey]);

  if (!summary || (!summary.in_russia && summary.days_used === 0)) return null;

  const level = stayLevel(summary);
  const { color, bg } = LEVEL_COLORS[level];
  const left = summary.days_to_leave ?? 0;

  return (
    <Card style={level !== 'ok' ? { borderWidth: 1.5, borderColor: color } : undefined}>
      <SectionHeader icon="airplane" title={t('russiaStay.title')} color={color} bg={bg} />
      {summary.in_russia ? (
        <>
          <View style={styles.row}>
            <View style={styles.cell}>
              <Text style={styles.big}>{t('russiaStay.day', { day: summary.day_of_stay })}</Text>
            </View>
            <View style={styles.cell}>
              <Text style={typography.label}>{t('russiaStay.leaveBy')}</Text>
              <Text style={styles.big}>{dmy(summary.must_leave_by)}</Text>
            </View>
          </View>
          <Text style={[styles.status, { color }]}>
            {level === 'over'
              ? t('russiaStay.overstay', { n: summary.overstay_days || -left })
              : left === 0
                ? t('russiaStay.leaveToday')
                : t('russiaStay.daysLeft', { n: left })}
          </Text>
        </>
      ) : (
        <>
          <Text style={typography.body}>{t('russiaStay.outside', { n: summary.days_used })}</Text>
          <Text style={typography.body}>{t('russiaStay.available', { n: Math.max(0, summary.days_available) })}</Text>
        </>
      )}
      <Text style={typography.caption}>{t('russiaStay.rule')}</Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: spacing.md },
  cell: { flex: 1, justifyContent: 'flex-end' },
  big: { fontSize: 24, fontWeight: '800', color: palette.ink },
  status: { fontSize: 16, fontWeight: '700' },
});
