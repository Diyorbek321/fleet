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

## Running the driver app in a browser

The app is built for phones, but it also exports to the web. That is what the
training video is recorded from, and it is a quick way to look at the driver's
screens without an APK or an emulator.

```bash
npx expo export -p web          # writes ./dist
cd dist && python3 -m http.server 4175 --bind 127.0.0.1
```

Point it at a backend with `EXPO_PUBLIC_API_URL` at export time:

```bash
EXPO_PUBLIC_API_URL=http://127.0.0.1:8003 npx expo export -p web
```

**What the web build does not do.** Background location is native-only:
`expo-task-manager` registers a task the operating system runs while the app is
closed, and a browser tab that is not open cannot report anything.
`src/lib/location-task.web.ts` therefore tracks only while the tab is open and
in the foreground, using the browser's Geolocation API, and never reports
`granted-background`. Push notifications are likewise Android/iOS only. The web
build is for demonstrations and for a dispatcher checking the driver view — not
a substitute for the app on a real run.

## Recording the walkthrough video

```bash
# 1. a backend with the Uzbek demo tenant and a driver login
cd ../backend
DEMO_PASSWORD='...' python seed_demo_uz.py --reset
DEMO_PASSWORD='...' python seed_demo_driver.py     # links haydovchi@silkroad.uz

# 2. the web build, served, pointed at that backend
cd ../mobile
EXPO_PUBLIC_API_URL=http://127.0.0.1:8003 npx expo export -p web
(cd dist && python3 -m http.server 4175 --bind 127.0.0.1 &)

# 3. record
node scripts/record-demo.mjs                        # → demo-video/*.webm

# 4. to MP4, which plays everywhere including Telegram
ffmpeg -i demo-video/*.webm -c:v libx264 -preset slow -crf 23 \
  -pix_fmt yuv420p -movflags +faststart -r 25 demo-video/haydovchi-qollanma.mp4
```

The script resets the demo driver's shift over the API before it starts, so a
second take opens on the same screen as the first. Re-run `seed_demo_uz.py
--reset` **and** `seed_demo_driver.py` together for a fully clean slate — the
reset deletes `drivers` rows and leaves the login pointing at nobody, which
makes every `/api/me/*` call 403 for a reason nothing on screen explains.
