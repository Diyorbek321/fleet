import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import en from './locales/en.json';
import uz from './locales/uz.json';
import ru from './locales/ru.json';

export const SUPPORTED_LANGUAGES = [
  { code: 'ru', label: 'Русский' },
  { code: 'uz', label: 'O‘zbekcha' },
  { code: 'en', label: 'English' },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

/** The language everyone gets until they pick another one themselves. */
export const DEFAULT_LANGUAGE: LanguageCode = 'ru';

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      uz: { translation: uz },
      ru: { translation: ru },
    },
    fallbackLng: DEFAULT_LANGUAGE,
    supportedLngs: SUPPORTED_LANGUAGES.map((l) => l.code),
    interpolation: { escapeValue: false },
    detection: {
      // Only the saved choice is consulted. The browser locale is deliberately
      // not in the chain: this panel is sold to Russian-speaking fleets, and a
      // laptop shipped with an English Windows must not decide the language for
      // a dispatcher who never asked for it.
      order: ['localStorage'],
      caches: ['localStorage'],
      lookupLocalStorage: 'fleet_language',
    },
  });

export default i18n;
