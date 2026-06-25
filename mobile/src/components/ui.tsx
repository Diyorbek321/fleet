import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { palette, radius, shadow, spacing, typography } from '../theme/theme';
import { haptics } from '../lib/haptics';

type IconName = keyof typeof Ionicons.glyphMap;

/** Elevated white surface — the base building block of every screen. */
export function Card({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return <View style={[ui.card, style]}>{children}</View>;
}

/** Small tinted circle holding an icon — used in section headers and stat tiles. */
export function IconCircle({
  icon,
  color = palette.brand,
  bg = palette.brandLight,
  size = 38,
}: {
  icon: IconName;
  color?: string;
  bg?: string;
  size?: number;
}) {
  return (
    <View
      style={[
        ui.iconCircle,
        { width: size, height: size, borderRadius: size / 2, backgroundColor: bg },
      ]}
    >
      <Ionicons name={icon} size={size * 0.5} color={color} />
    </View>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <Text style={ui.sectionTitle}>{children}</Text>;
}

/** Title row with a leading icon chip and an optional trailing action. */
export function SectionHeader({
  icon,
  title,
  color,
  bg,
  right,
}: {
  icon: IconName;
  title: string;
  color?: string;
  bg?: string;
  right?: React.ReactNode;
}) {
  return (
    <View style={ui.sectionHeader}>
      <IconCircle icon={icon} color={color} bg={bg} size={34} />
      <Text style={ui.sectionHeaderTitle}>{title}</Text>
      {right ? <View style={ui.sectionHeaderRight}>{right}</View> : null}
    </View>
  );
}

export function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={ui.rowItem}>
      <Text style={ui.rowLabel}>{label}</Text>
      <Text style={ui.rowValue}>{value}</Text>
    </View>
  );
}

export function Divider() {
  return <View style={ui.divider} />;
}

export function Muted({ children }: { children: React.ReactNode }) {
  return <Text style={ui.muted}>{children}</Text>;
}

/** Colored status chip (in queue / late / open / resolved …). */
export function Pill({
  label,
  color = palette.brand,
  bg = palette.brandLight,
}: {
  label: string;
  color?: string;
  bg?: string;
}) {
  return (
    <View style={[ui.pill, { backgroundColor: bg }]}>
      <View style={[ui.pillDot, { backgroundColor: color }]} />
      <Text style={[ui.pillText, { color }]}>{label}</Text>
    </View>
  );
}

/** Compact metric card (icon + big number + label). Designed for side-by-side rows. */
export function StatTile({
  icon,
  value,
  label,
  color = palette.brand,
  bg = palette.brandLight,
}: {
  icon: IconName;
  value: string;
  label: string;
  color?: string;
  bg?: string;
}) {
  return (
    <View style={ui.statTile}>
      <IconCircle icon={icon} color={color} bg={bg} size={36} />
      <Text style={ui.statValue}>{value}</Text>
      <Text style={ui.statLabel}>{label}</Text>
    </View>
  );
}

export function Loading() {
  return (
    <View style={ui.center}>
      <ActivityIndicator size="large" color={palette.brand} />
    </View>
  );
}

/** Friendly placeholder for empty lists. */
export function EmptyState({
  icon,
  title,
  subtitle,
}: {
  icon: IconName;
  title: string;
  subtitle?: string;
}) {
  return (
    <View style={ui.empty}>
      <IconCircle icon={icon} color={palette.faint} bg={palette.surfaceAlt} size={52} />
      <Text style={ui.emptyTitle}>{title}</Text>
      {subtitle ? <Text style={ui.emptySubtitle}>{subtitle}</Text> : null}
    </View>
  );
}

export function ErrorBox({
  message,
  onRetry,
  retryLabel,
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <View style={[ui.card, ui.errorCard]}>
      <View style={ui.errorHeader}>
        <Ionicons name="alert-circle" size={20} color={palette.danger} />
        <Text style={ui.errorText}>{message}</Text>
      </View>
      {onRetry && (
        <Pressable
          style={ui.retryBtn}
          onPress={() => {
            haptics.tap();
            onRetry();
          }}
        >
          <Ionicons name="refresh" size={16} color={palette.danger} />
          <Text style={ui.retryText}>{retryLabel ?? 'Retry'}</Text>
        </Pressable>
      )}
    </View>
  );
}

export function Field(props: TextInputProps & { label: string; icon?: IconName }) {
  const { label, icon, style, ...input } = props;
  return (
    <View style={{ gap: spacing.xs }}>
      <Text style={ui.label}>{label}</Text>
      <View style={ui.inputWrap}>
        {icon ? (
          <Ionicons name={icon} size={18} color={palette.faint} style={ui.inputIcon} />
        ) : null}
        <TextInput
          style={[ui.input, icon && ui.inputWithIcon, style]}
          placeholderTextColor={palette.faint}
          {...input}
        />
      </View>
    </View>
  );
}

type ButtonVariant = 'primary' | 'outline' | 'danger' | 'success' | 'ghost';

const VARIANT_STYLES: Record<ButtonVariant, { container: ViewStyle; text: { color: string } }> = {
  primary: { container: { backgroundColor: palette.brand }, text: { color: palette.white } },
  outline: {
    container: { borderWidth: 1.5, borderColor: palette.brand, backgroundColor: palette.white },
    text: { color: palette.brand },
  },
  danger: {
    container: { backgroundColor: palette.dangerBg, borderWidth: 1, borderColor: palette.dangerLine },
    text: { color: palette.danger },
  },
  success: { container: { backgroundColor: palette.success }, text: { color: palette.white } },
  ghost: { container: { backgroundColor: palette.surfaceAlt }, text: { color: palette.inkSoft } },
};

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled,
  loading,
  icon,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  loading?: boolean;
  icon?: IconName;
  style?: StyleProp<ViewStyle>;
}) {
  const v = VARIANT_STYLES[variant];
  const inactive = disabled || loading;
  return (
    <Pressable
      style={({ pressed }) => [
        ui.btn,
        v.container,
        variant === 'primary' && shadow.sm,
        pressed && !inactive && ui.btnPressed,
        inactive && ui.btnDisabled,
        style,
      ]}
      disabled={inactive}
      onPress={() => {
        haptics.press();
        onPress();
      }}
    >
      {loading ? (
        <ActivityIndicator color={v.text.color} />
      ) : (
        <View style={ui.btnInner}>
          {icon ? <Ionicons name={icon} size={18} color={v.text.color} /> : null}
          <Text style={[ui.btnText, v.text]}>{label}</Text>
        </View>
      )}
    </Pressable>
  );
}

export const ui = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: palette.background,
  },
  card: {
    backgroundColor: palette.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
    ...shadow.md,
  },
  iconCircle: { alignItems: 'center', justifyContent: 'center' },
  sectionTitle: typography.heading,
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  sectionHeaderTitle: { ...typography.heading, flex: 1 },
  sectionHeaderRight: { marginLeft: 'auto' },
  rowItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: spacing.md,
  },
  rowLabel: { ...typography.body, color: palette.muted },
  rowValue: {
    fontSize: 15,
    color: palette.ink,
    fontWeight: '700',
    flexShrink: 1,
    textAlign: 'right',
  },
  divider: { height: 1, backgroundColor: palette.line, marginVertical: spacing.xs },
  muted: typography.body,
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'flex-start',
    paddingVertical: 6,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
  },
  pillDot: { width: 8, height: 8, borderRadius: 4 },
  pillText: { fontSize: 13, fontWeight: '700' },
  statTile: {
    flex: 1,
    backgroundColor: palette.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
    ...shadow.md,
  },
  statValue: { ...typography.statValue, marginTop: spacing.xs },
  statLabel: { ...typography.label, color: palette.muted },
  empty: { alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.lg },
  emptyTitle: { ...typography.heading, color: palette.inkSoft },
  emptySubtitle: { ...typography.caption, textAlign: 'center' },
  errorCard: {
    backgroundColor: palette.dangerBg,
    borderWidth: 1,
    borderColor: palette.dangerLine,
  },
  errorHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  errorText: { color: '#b91c1c', fontWeight: '600', flex: 1 },
  retryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'flex-start',
    paddingVertical: spacing.xs,
  },
  retryText: { color: palette.danger, fontWeight: '700' },
  label: typography.label,
  inputWrap: { justifyContent: 'center' },
  inputIcon: { position: 'absolute', left: 14, zIndex: 1 },
  input: {
    borderWidth: 1,
    borderColor: palette.line,
    backgroundColor: palette.surfaceAlt,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: palette.ink,
  },
  inputWithIcon: { paddingLeft: 42 },
  btn: {
    paddingVertical: 14,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnInner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  btnText: { fontWeight: '700', fontSize: 15 },
  btnPressed: { opacity: 0.85, transform: [{ scale: 0.985 }] },
  btnDisabled: { opacity: 0.45 },
});
