/**
 * The in-app notice shown before the OS asks for background location.
 *
 * Google Play requires a "prominent disclosure": the app must say, in its own
 * UI and before the system prompt, what location it collects, that it does so
 * while the app is closed, and what for. Without it the background-location
 * declaration is rejected at review, whatever the declaration form says.
 */
import { Alert } from 'react-native';

type DisclosureKey =
  | 'tracking.disclosureTitle'
  | 'tracking.disclosureBody'
  | 'tracking.disclosureDecline'
  | 'tracking.disclosureAccept';
type Translate = (key: DisclosureKey) => string;

/**
 * Only where the system prompt is still coming. A driver who already granted
 * "Allow all the time" has seen it; the web build never tracks in the
 * background, so there is nothing to disclose there (and Alert buttons are a
 * no-op on web, which would leave the toggle hanging).
 */
export function needsDisclosure(platform: string, backgroundStatus: string): boolean {
  return platform !== 'web' && backgroundStatus !== 'granted';
}

/** Show the notice; resolves true only when the driver explicitly agrees. */
export function confirmLocationDisclosure(t: Translate): Promise<boolean> {
  return new Promise((resolve) => {
    Alert.alert(
      t('tracking.disclosureTitle'),
      t('tracking.disclosureBody'),
      [
        { text: t('tracking.disclosureDecline'), style: 'cancel', onPress: () => resolve(false) },
        { text: t('tracking.disclosureAccept'), onPress: () => resolve(true) },
      ],
      { cancelable: false },
    );
  });
}
