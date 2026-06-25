# Fleet Watch — Driver App (Expo)

React Native (Expo) mobile app for drivers. Talks to the backend's self-scoped
`/api/me/*` endpoints.

## Quickstart

```bash
cd mobile
npm install
npm start          # then press i (iOS), a (Android), or scan the QR in Expo Go
```

Set the API URL in `app.json` → `expo.extra.apiUrl` (defaults to `http://localhost:8000`).

## Multi-language (EN / UZ / RU)

Built on `i18next` + `react-i18next`, mirroring the web app but adapted for React Native.

| Piece | File |
|---|---|
| Init + language resolution + `setLanguage()` | `src/i18n/index.ts` |
| Translations (source of truth = `en.json`) | `src/i18n/locales/{en,uz,ru}.json` |
| Language picker UI | `src/components/LanguageSwitcher.tsx` |
| `t()` key type-safety | `src/i18n/i18next.d.ts` |

**How it resolves the active language at launch:**
1. The user's saved choice (`AsyncStorage`, key `fleet_driver_language`)
2. The device locale (`expo-localization`)
3. English fallback

**Usage in a screen:**

```tsx
import { useTranslation } from 'react-i18next';

function HomeScreen() {
  const { t } = useTranslation();
  return <Text>{t('home.assignedTruck')}</Text>;
}
```

**Switch language anywhere:**

```tsx
import { setLanguage } from '@/i18n';
await setLanguage('uz');   // persists + updates the whole UI live
```

Or drop in the ready-made `<LanguageSwitcher />`.

### Adding a key
Add it to `en.json` first, then `uz.json` and `ru.json` with the **same path**.
All three files must stay in sync (79 keys today). Quick check:

```bash
cd src/i18n/locales && python3 - <<'PY'
import json
def flat(d,p=''):
    s=set()
    for k,v in d.items():
        key=f'{p}.{k}' if p else k
        s|=flat(v,key) if isinstance(v,dict) else {key}
    return s
base=flat(json.load(open('en.json')))
for L in ('uz','ru'):
    diff=base^flat(json.load(open(f'{L}.json')))
    print(L, 'OK' if not diff else f'MISMATCH: {sorted(diff)}')
PY
```

### Adding a language
1. Create `src/i18n/locales/<code>.json` (copy `en.json`, translate values).
2. Register it in `SUPPORTED_LANGUAGES` and `resources` in `src/i18n/index.ts`.

## Status
- [x] Multi-language system (EN / UZ / RU) — init, persistence, device detection, switcher
- [ ] Auth / login screen (Stage B)
- [ ] Tab navigation + the six MVP screens (Stage C)
