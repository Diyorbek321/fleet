import 'i18next';
import en from './locales/en.json';

/**
 * Augments i18next so `t('...')` keys are type-checked and auto-completed
 * against the English locale (the source of truth).
 */
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation';
    resources: { translation: typeof en };
  }
}
