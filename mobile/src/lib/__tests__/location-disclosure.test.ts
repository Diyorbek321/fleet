/**
 * Google Play's prominent-disclosure rule: before the OS asks for background
 * location, the app itself must say what it collects and why. An app that
 * jumps straight to the system prompt is rejected at review.
 */
import { Alert } from 'react-native';

import { confirmLocationDisclosure, needsDisclosure } from '../location-disclosure';

const t = (key: string) => key;

describe('needsDisclosure', () => {
  it('is shown on a phone that has not granted background location', () => {
    expect(needsDisclosure('android', 'undetermined')).toBe(true);
    expect(needsDisclosure('android', 'denied')).toBe(true);
    expect(needsDisclosure('ios', 'undetermined')).toBe(true);
  });

  it('is skipped once background location is already granted', () => {
    expect(needsDisclosure('android', 'granted')).toBe(false);
  });

  it('is skipped on the web build, which never tracks in the background', () => {
    expect(needsDisclosure('web', 'undetermined')).toBe(false);
  });
});

describe('confirmLocationDisclosure', () => {
  const press = (label: string) => {
    const buttons = (Alert.alert as jest.Mock).mock.calls.at(-1)[2];
    buttons.find((b: { text: string }) => b.text === label).onPress();
  };

  beforeEach(() => {
    jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  });

  it('resolves true when the driver accepts', async () => {
    const answer = confirmLocationDisclosure(t);
    press('tracking.disclosureAccept');
    await expect(answer).resolves.toBe(true);
  });

  it('resolves false when the driver declines', async () => {
    const answer = confirmLocationDisclosure(t);
    press('tracking.disclosureDecline');
    await expect(answer).resolves.toBe(false);
  });

  it('cannot be dismissed by tapping outside, so the choice is explicit', () => {
    confirmLocationDisclosure(t);
    const options = (Alert.alert as jest.Mock).mock.calls.at(-1)[3];
    expect(options).toEqual({ cancelable: false });
  });
});
