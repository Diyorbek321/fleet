# Building & testing the Driver app on your phone

You have two paths. **Start with Path A — it gets the app on your phone in ~2 minutes
with no build.** Use Path B only when you want a real installable `.apk`.

---

## Prerequisites (both paths)
- The backend running and reachable from your phone (see "Point the app at your backend").
- Node.js installed on your computer.
- From the `mobile/` folder: `npm install` (run once).

### Point the app at your backend
The app reads the API URL from `app.json` → `expo.extra.apiUrl` (default
`http://localhost:8000`). **`localhost` does NOT work from a real phone** — it means the
phone itself. Use your computer's LAN IP so the phone can reach the backend:

1. Find your computer's IP (e.g. `192.168.1.50`):
   - Linux/macOS: `hostname -I` or `ipconfig getifaddr en0`
2. Edit `mobile/app.json`:
   ```json
   "extra": { "apiUrl": "http://192.168.1.50:8000" }
   ```
3. Start the backend bound to all interfaces so the phone can connect:
   ```bash
   cd backend
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
4. Phone and computer must be on the **same Wi-Fi**.

---

## Path A — Test instantly with Expo Go (recommended)

Every library this app uses (navigation, location, async-storage, localization) runs in
**Expo Go**, so no APK is needed to test.

1. Install **Expo Go** on your phone (Google Play / App Store).
2. On your computer, in `mobile/`:
   ```bash
   npx expo start
   ```
3. A QR code appears in the terminal.
   - **Android:** open Expo Go → "Scan QR code" → scan it.
   - **iOS:** open the Camera app → point at the QR → tap the banner.
4. The app loads on your phone. Sign in with a driver account (create one via the backend:
   `POST /api/drivers/{id}/create-login`).
5. Edit code → it hot-reloads on the phone instantly.

> If the phone can't connect, run `npx expo start --tunnel` (works across networks/firewalls).

---

## Path B — Build a real installable APK (EAS Build, cloud)

This produces a `.apk` you can install on any Android phone. It builds in Expo's cloud
(free tier) — **no Android SDK needed on your machine** — but requires a free Expo account.

1. Install the EAS CLI and log in (uses *your* Expo account):
   ```bash
   npm install -g eas-cli
   eas login
   ```
2. From `mobile/`, link the project (creates an EAS project id, writes it into `app.json`):
   ```bash
   eas init
   ```
3. Build the APK (the `preview` profile in `eas.json` is set to `buildType: apk`):
   ```bash
   eas build --platform android --profile preview
   ```
4. When it finishes (~10–20 min), the terminal prints a **download URL**. Open it on your
   phone's browser, or scan the QR EAS shows, to download `app-release.apk`.

### Install the APK on your phone
1. Download the `.apk` to the phone.
2. Tap it. Android will ask to allow installing from this source:
   **Settings → Apps → Special access → Install unknown apps →** enable for your browser/Files app.
3. Confirm install → open **Fleet Watch Driver**.
4. Make sure `apiUrl` in `app.json` pointed at a backend the phone can reach **before** you
   built (for a field test, that's a deployed/public backend URL, not `localhost`).

---

## Path C — Fully local APK (advanced, needs Android SDK)

Only if you want to build without Expo's cloud. Requires Android SDK + `ANDROID_HOME` set.
```bash
cd mobile
npx expo prebuild --platform android
cd android
./gradlew assembleRelease
# APK at: android/app/build/outputs/apk/release/app-release.apk
```

---

## Which should I use?
- **Just testing the app / iterating:** Path A (Expo Go). Fastest, no build.
- **Giving drivers an installable app, or testing native release behavior:** Path B (EAS APK).
- **You already have Android Studio / SDK and want offline builds:** Path C.
