/**
 * Date formatting that follows the interface language.
 *
 * `date-fns` defaults to English, so every `formatDistanceToNow` in the panel
 * used to render "2 hours ago" next to Russian labels. Components import these
 * wrappers instead of `date-fns` directly, which keeps the locale decision in
 * one place and makes a language switch reach the timestamps too.
 */
import {
  format as fnsFormat,
  formatDistanceToNow as fnsFormatDistanceToNow,
  type FormatDistanceToNowOptions,
  type FormatOptions,
} from 'date-fns';
import { enUS, ru, uz } from 'date-fns/locale';
import type { Locale } from 'date-fns';

import i18n, { DEFAULT_LANGUAGE } from '@/i18n';

const LOCALES: Record<string, Locale> = { ru, uz, en: enUS };

/** The `date-fns` locale matching the active interface language. */
export function dateLocale(): Locale {
  const active = (i18n.resolvedLanguage ?? i18n.language ?? DEFAULT_LANGUAGE).split('-')[0];
  return LOCALES[active] ?? LOCALES[DEFAULT_LANGUAGE];
}

export function formatDistanceToNow(
  date: Date | number | string,
  options?: FormatDistanceToNowOptions,
): string {
  return fnsFormatDistanceToNow(new Date(date), { ...options, locale: dateLocale() });
}

export function format(
  date: Date | number | string,
  formatStr: string,
  options?: FormatOptions,
): string {
  return fnsFormat(new Date(date), formatStr, { ...options, locale: dateLocale() });
}

export { addDays, differenceInDays, isAfter, isBefore } from 'date-fns';
