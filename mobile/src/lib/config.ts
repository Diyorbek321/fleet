import Constants from 'expo-constants';

/**
 * Backend base URL.
 *
 * Resolution order (first defined wins):
 *   1. `process.env.EXPO_PUBLIC_API_URL` — injected per EAS build profile
 *      (see `eas.json` → build.<profile>.env). This is how shipped builds
 *      (development / preview / production) get their HTTPS backend host.
 *      Expo inlines any `EXPO_PUBLIC_*` var at bundle time.
 *   2. `app.json` → expo.extra.apiUrl — convenience override for `npm start`
 *      against a LAN IP or the Android-emulator loopback. NEVER a production URL.
 *   3. `http://localhost:8000` — last-resort local-dev fallback.
 *
 * The emulator-only `http://10.0.2.2:8000` value lives in app.json's `extra`
 * and is used ONLY for local development — production gets an HTTPS URL from
 * the EAS `production` build profile's `EXPO_PUBLIC_API_URL`.
 */
export const API_URL =
  (process.env.EXPO_PUBLIC_API_URL as string | undefined) ??
  (Constants.expoConfig?.extra?.apiUrl as string | undefined) ??
  'http://localhost:8000';
