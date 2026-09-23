import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getLocales } from 'expo-localization';

import en from './locales/en.json';
import uz from './locales/uz.json';
import ru from './locales/ru.json';

export const SUPPORTED_LANGUAGES = [
  { code: 'ru', label: 'Русский' },
  { code: 'uz', label: 'O‘zbekcha' },
  { code: 'en', label: 'English' },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

/** The language a driver gets before they have chosen one. */
export const DEFAULT_LANGUAGE: LanguageCode = 'ru';

/** Where the driver's chosen language is persisted. Also read by the
 *  headless background-location task, which cannot use this i18next instance. */
export const LANGUAGE_STORAGE_KEY = 'fleet_driver_language';
const STORAGE_KEY = LANGUAGE_STORAGE_KEY;

const isSupported = (code: string | null | undefined): code is LanguageCode =>
  !!code && SUPPORTED_LANGUAGES.some((l) => l.code === code);

/**
 * The device's preferred language, falling back to Russian.
 *
 * A phone set to Kazakh, Turkish or English gets Russian rather than English:
 * these trucks run Uzbekistan–Kazakhstan–Russia, and Russian is the language
 * every driver on that route reads, whatever their handset was sold with.
 */
function deviceLanguage(): LanguageCode {
  const code = getLocales()[0]?.languageCode ?? DEFAULT_LANGUAGE;
  return isSupported(code) ? code : DEFAULT_LANGUAGE;
}

/**
 * Initialise i18next once at app start. Resolves the active language from the
 * user's saved choice (AsyncStorage), then the device locale, then English.
 * Call this and await it before rendering the app tree.
 */
export async function initI18n(): Promise<typeof i18n> {
  let lng: LanguageCode = deviceLanguage();
  try {
    const saved = await AsyncStorage.getItem(STORAGE_KEY);
    if (isSupported(saved)) {
      lng = saved;
    }
  } catch {
    // Storage unavailable — fall back to device language.
  }

  await i18n.use(initReactI18next).init({
    resources: {
      en: { translation: en },
      uz: { translation: uz },
      ru: { translation: ru },
    },
    lng,
    fallbackLng: DEFAULT_LANGUAGE,
    supportedLngs: SUPPORTED_LANGUAGES.map((l) => l.code),
    interpolation: { escapeValue: false },
    // RN runtimes may lack full Intl.PluralRules; v4 keeps plural handling safe.
    compatibilityJSON: 'v4',
  });

  return i18n;
}

/** Switch language at runtime and persist the choice for next launch. */
export async function setLanguage(code: LanguageCode): Promise<void> {
  await i18n.changeLanguage(code);
  try {
    await AsyncStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Non-fatal: language still changes for this session.
  }
}

export default i18n;
