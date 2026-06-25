import React from 'react';
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

import { palette, radius, spacing, typography } from '../theme/theme';

type IconName = keyof typeof Ionicons.glyphMap;

/**
 * Standard tab screen scaffold: a gradient hero header (title + optional
 * subtitle/eyebrow and a trailing slot) over a scrollable, pull-to-refresh
 * content area. Content overlaps the header slightly with rounded corners so
 * the page reads as a single layered surface rather than flat bands.
 */
export function Screen({
  title,
  subtitle,
  eyebrow,
  icon,
  right,
  refreshing,
  onRefresh,
  children,
  contentStyle,
}: {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  icon?: IconName;
  right?: React.ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
  children: React.ReactNode;
  contentStyle?: ViewStyle;
}) {
  const insets = useSafeAreaInsets();

  return (
    <View style={styles.root}>
      <LinearGradient
        colors={palette.gradient}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={[styles.header, { paddingTop: insets.top + spacing.md }]}
      >
        <View style={styles.headerRow}>
          <View style={styles.headerText}>
            {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
            <View style={styles.titleRow}>
              {icon ? <Ionicons name={icon} size={24} color={palette.white} /> : null}
              <Text style={styles.title}>{title}</Text>
            </View>
            {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
          </View>
          {right ? <View style={styles.right}>{right}</View> : null}
        </View>
      </LinearGradient>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[
          styles.content,
          { paddingBottom: insets.bottom + spacing.xxxl },
          contentStyle,
        ]}
        showsVerticalScrollIndicator={false}
        refreshControl={
          onRefresh ? (
            <RefreshControl
              refreshing={!!refreshing}
              onRefresh={onRefresh}
              tintColor={palette.brand}
              colors={[palette.brand]}
            />
          ) : undefined
        }
      >
        {children}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.background },
  header: {
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.xxxl + spacing.md,
    borderBottomLeftRadius: radius.xl,
    borderBottomRightRadius: radius.xl,
  },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md },
  headerText: { flex: 1, gap: 2 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  eyebrow: {
    color: 'rgba(255,255,255,0.75)',
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  title: { ...typography.title, color: palette.white },
  subtitle: { color: 'rgba(255,255,255,0.85)', fontSize: 14, fontWeight: '500', marginTop: 2 },
  right: { marginLeft: 'auto' },
  scroll: { flex: 1, marginTop: -spacing.xxl },
  content: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xs,
    gap: spacing.lg,
  },
});
