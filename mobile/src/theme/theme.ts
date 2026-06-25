import { Platform, TextStyle, ViewStyle } from 'react-native';

/**
 * Central design tokens for the Fleet Watch driver app.
 *
 * Everything visual (colors, spacing, radii, typography, shadows) is defined
 * here so screens stay consistent and the look can be tuned in one place.
 * The palette is a "modern light" system: a soft slate background, white
 * elevated cards, a blue brand accent, and semantic colors for status.
 */

export const palette = {
  // Brand
  brand: '#2563eb',
  brandDark: '#1d4ed8',
  brandLight: '#dbeafe',
  // Gradient used in screen headers (brand → indigo)
  gradient: ['#2563eb', '#4f46e5'] as const,
  gradientNavy: ['#0f172a', '#1e293b'] as const,

  // Neutrals (slate scale)
  ink: '#0f172a',
  inkSoft: '#334155',
  muted: '#64748b',
  faint: '#94a3b8',
  line: '#e2e8f0',
  surface: '#ffffff',
  surfaceAlt: '#f1f5f9',
  background: '#f6f8fc',
  white: '#ffffff',

  // Semantic
  success: '#16a34a',
  successBg: '#dcfce7',
  warning: '#d97706',
  warningBg: '#fef3c7',
  danger: '#dc2626',
  dangerBg: '#fef2f2',
  dangerLine: '#fecaca',
  info: '#2563eb',
  infoBg: '#dbeafe',

  // Accent colors used to tint stat tiles / section icons per feature
  fuel: '#f59e0b',
  fuelBg: '#fef3c7',
  mileage: '#0ea5e9',
  mileageBg: '#e0f2fe',
  queue: '#2563eb',
  queueBg: '#dbeafe',
  safety: '#16a34a',
  safetyBg: '#dcfce7',
  maintenance: '#8b5cf6',
  maintenanceBg: '#ede9fe',
  expense: '#0d9488',
  expenseBg: '#ccfbf1',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  pill: 999,
} as const;

export const typography: Record<string, TextStyle> = {
  display: { fontSize: 28, fontWeight: '800', color: palette.ink, letterSpacing: -0.5 },
  title: { fontSize: 22, fontWeight: '800', color: palette.ink, letterSpacing: -0.3 },
  heading: { fontSize: 17, fontWeight: '700', color: palette.ink },
  body: { fontSize: 15, fontWeight: '500', color: palette.inkSoft },
  label: { fontSize: 13, fontWeight: '600', color: palette.muted },
  caption: { fontSize: 12, fontWeight: '500', color: palette.faint },
  statValue: { fontSize: 24, fontWeight: '800', color: palette.ink, letterSpacing: -0.5 },
};

/** Soft elevation used by cards. Cross-platform (iOS shadow + Android elevation). */
export const shadow: Record<'sm' | 'md' | 'lg', ViewStyle> = {
  sm: Platform.select({
    ios: {
      shadowColor: '#0f172a',
      shadowOpacity: 0.05,
      shadowRadius: 6,
      shadowOffset: { width: 0, height: 2 },
    },
    default: { elevation: 1 },
  }) as ViewStyle,
  md: Platform.select({
    ios: {
      shadowColor: '#0f172a',
      shadowOpacity: 0.08,
      shadowRadius: 14,
      shadowOffset: { width: 0, height: 6 },
    },
    default: { elevation: 3 },
  }) as ViewStyle,
  lg: Platform.select({
    ios: {
      shadowColor: '#1e3a8a',
      shadowOpacity: 0.18,
      shadowRadius: 20,
      shadowOffset: { width: 0, height: 10 },
    },
    default: { elevation: 6 },
  }) as ViewStyle,
};

export const theme = { palette, spacing, radius, typography, shadow };
export type Theme = typeof theme;
