import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { palette, radius, spacing, typography } from '../theme/theme';
import { haptics } from '../lib/haptics';
import { Button } from './ui';
import {
  placesFor,
  suggestedStages,
  type StagePlace,
  type TripStage,
} from '../lib/trips';

interface StagePickerProps {
  current: TripStage | null;
  busy?: boolean;
  onPick: (stage: TripStage, place: StagePlace) => void;
}

/**
 * Two taps: what happened, then where.
 *
 * Split in two because the place is not a property of the stage — the same
 * "arrived at the border" happens at UZ–KZ and again at KZ–RU on one run, and
 * the crossing is the only thing that tells them apart afterwards. Asking in
 * one combined list would mean 9 x 3 buttons on a phone held at a weighbridge.
 */
export function StagePicker({ current, busy, onPick }: StagePickerProps) {
  const { t } = useTranslation();
  const [stage, setStage] = useState<TripStage | null>(null);

  const stages = suggestedStages(current);

  if (stage) {
    return (
      <View style={styles.block}>
        <Text style={styles.prompt}>{t('trips.placePrompt')}</Text>
        <Text style={styles.chosen}>{t(`trips.stage.${stage}`)}</Text>
        <View style={styles.chips}>
          {placesFor(stage).map((place) => (
            <Chip
              key={place}
              label={t(`trips.place.${place}`)}
              disabled={busy}
              onPress={() => {
                onPick(stage, place);
                setStage(null);
              }}
            />
          ))}
        </View>
        <Button
          label={t('common.cancel')}
          variant="ghost"
          icon="chevron-back"
          onPress={() => setStage(null)}
        />
      </View>
    );
  }

  return (
    <View style={styles.block}>
      <Text style={styles.prompt}>{t('trips.stagePrompt')}</Text>
      {stages.map((s) => (
        <Pressable
          key={s}
          style={({ pressed }) => [styles.stageRow, pressed && styles.stageRowPressed]}
          disabled={busy}
          onPress={() => {
            void haptics.press();
            setStage(s);
          }}
        >
          <Text style={styles.stageText}>{t(`trips.stage.${s}`)}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function Chip({
  label,
  onPress,
  disabled,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      style={({ pressed }) => [styles.chip, pressed && styles.chipPressed, disabled && styles.chipOff]}
      disabled={disabled}
      onPress={() => {
        void haptics.press();
        onPress();
      }}
    >
      <Text style={styles.chipText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  block: { marginTop: spacing.sm, gap: spacing.xs },
  prompt: { ...typography.caption, marginBottom: spacing.xs },
  chosen: { ...typography.body, fontWeight: '700', color: palette.ink, marginBottom: spacing.xs },
  // Full-width rows, not a wrapped grid: this is tapped in a cab, often with
  // gloves on, so every target is the width of the card.
  stageRow: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    backgroundColor: palette.surfaceAlt,
  },
  stageRowPressed: { backgroundColor: palette.brandLight },
  stageText: { ...typography.body, color: palette.ink, fontWeight: '600' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.xs },
  chip: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    backgroundColor: palette.brand,
  },
  chipPressed: { backgroundColor: palette.brandDark },
  chipOff: { opacity: 0.5 },
  chipText: { ...typography.body, color: '#ffffff', fontWeight: '700' },
});
