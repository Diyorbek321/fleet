/**
 * Release signing, which Expo's own plugins do not write — kept as a config
 * plugin so `expo prebuild --clean` reproduces it instead of wiping it.
 *
 * Signs release builds from android/keystore.properties (or FLEETWATCH_* env).
 * Prebuild signs them with the debug key by default; such an APK will not
 * install over the one drivers already have, and Play rejects it. The keystore
 * and its passwords are gitignored and live only on the release machine —
 * see BUILD.md.
 *
 * Also widens MainActivity's configChanges so tablets do not restart the app
 * on every window resize (see withTabletConfigChanges).
 *
 * (Firebase's default notification channel is set through expo-notifications'
 * own `defaultChannel` option in app.json: that plugin removes the meta-data
 * when the option is absent, so adding it here would be undone.)
 */
const { withAndroidManifest, withAppBuildGradle } = require('expo/config-plugins');

const SIGNING_MARKER = '// fleet-watch: release signing';

const RELEASE_SIGNING = `
        release {
            ${SIGNING_MARKER}
            def ksProps = new Properties()
            def ksPropsFile = rootProject.file('keystore.properties')
            if (ksPropsFile.exists()) {
                ksPropsFile.withInputStream { ksProps.load(it) }
            }
            storeFile file(ksProps.getProperty('storeFile', System.getenv('FLEETWATCH_STORE_FILE') ?: 'fleetwatch-release.keystore'))
            storePassword ksProps.getProperty('storePassword', System.getenv('FLEETWATCH_STORE_PASSWORD') ?: '')
            keyAlias ksProps.getProperty('keyAlias', System.getenv('FLEETWATCH_KEY_ALIAS') ?: 'fleetwatch')
            keyPassword ksProps.getProperty('keyPassword', System.getenv('FLEETWATCH_KEY_PASSWORD') ?: '')
        }`;

function withReleaseSigning(config) {
  return withAppBuildGradle(config, (cfg) => {
    let gradle = cfg.modResults.contents;
    if (gradle.includes(SIGNING_MARKER)) return cfg;

    // Add a release entry to signingConfigs, right after the debug one.
    gradle = gradle.replace(
      /(signingConfigs\s*\{\s*debug\s*\{[^}]*\})/,
      `$1${RELEASE_SIGNING}`,
    );
    // Point the release build type at it (prebuild points it at debug).
    gradle = gradle.replace(
      /(buildTypes\s*\{[\s\S]*?release\s*\{[\s\S]*?)signingConfig signingConfigs\.debug/,
      '$1signingConfig signingConfigs.release',
    );
    if (!gradle.includes('signingConfig signingConfigs.release')) {
      throw new Error('with-fleet-android: could not wire release signing into app/build.gradle');
    }
    cfg.modResults.contents = gradle;
    return cfg;
  });
}

// Config changes MainActivity handles itself instead of being torn down and
// recreated. Android 16 ignores the portrait lock on tablets (targetSdk 36,
// smallest width >= 600dp) and resizes the window itself; without
// smallestScreenSize/density in this list every such resize restarted the
// activity, and the whole app reloaded to a spinner every few seconds.
const TABLET_CONFIG_CHANGES = ['smallestScreenSize', 'density'];

function withTabletConfigChanges(config) {
  return withAndroidManifest(config, (cfg) => {
    const app = cfg.modResults.manifest.application?.[0];
    const main = app?.activity?.find((a) => a.$['android:name'] === '.MainActivity');
    if (!main) {
      throw new Error('with-fleet-android: MainActivity not found in AndroidManifest.xml');
    }
    const current = (main.$['android:configChanges'] ?? '').split('|').filter(Boolean);
    const missing = TABLET_CONFIG_CHANGES.filter((c) => !current.includes(c));
    main.$['android:configChanges'] = [...current, ...missing].join('|');
    return cfg;
  });
}

module.exports = function withFleetAndroid(config) {
  return withTabletConfigChanges(withReleaseSigning(config));
};
