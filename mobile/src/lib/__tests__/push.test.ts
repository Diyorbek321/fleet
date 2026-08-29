/**
 * Registering the device for push notifications.
 *
 * The whole notification path was dead from this end: the backend stored push
 * tokens and resolved them on every status change, but the app never called
 * `/api/me/push-token`, so the table was always empty. These cover the paths
 * that decide whether a driver ever hears from the platform.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

jest.mock('../api', () => ({ apiFetch: jest.fn(async () => ({})) }));

jest.mock('expo-notifications', () => ({
  getPermissionsAsync: jest.fn(async () => ({ granted: true, canAskAgain: true })),
  requestPermissionsAsync: jest.fn(async () => ({ granted: true })),
  getExpoPushTokenAsync: jest.fn(async () => ({ data: 'ExponentPushToken[test]' })),
  setNotificationChannelAsync: jest.fn(async () => undefined),
  AndroidImportance: { HIGH: 4 },
  AndroidNotificationVisibility: { PUBLIC: 1 },
}));

jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: { eas: { projectId: 'proj-1' } } }, easConfig: null },
}));

import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';

import { apiFetch } from '../api';
import { registerPushToken, unregisterPushToken } from '../push';

const mockFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

beforeEach(async () => {
  jest.clearAllMocks();
  await AsyncStorage.clear();
  // clearAllMocks resets recorded calls but NOT implementations, so a
  // mockRejectedValue set by one test would otherwise leak into the next.
  mockFetch.mockResolvedValue({} as never);
  (Notifications.getPermissionsAsync as jest.Mock).mockResolvedValue({
    granted: true,
    canAskAgain: true,
  });
  (Notifications.getExpoPushTokenAsync as jest.Mock).mockResolvedValue({
    data: 'ExponentPushToken[test]',
  });
  (Constants as any).expoConfig = { extra: { eas: { projectId: 'proj-1' } } };
});

describe('registerPushToken', () => {
  it('sends the token to the backend', async () => {
    const token = await registerPushToken();

    expect(token).toBe('ExponentPushToken[test]');
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/me/push-token',
      expect.objectContaining({ method: 'POST' }),
    );
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
    expect(body.token).toBe('ExponentPushToken[test]');
  });

  it('does nothing when the driver refused the permission', async () => {
    (Notifications.getPermissionsAsync as jest.Mock).mockResolvedValue({
      granted: false,
      canAskAgain: true,
    });
    (Notifications.requestPermissionsAsync as jest.Mock).mockResolvedValue({ granted: false });

    expect(await registerPushToken()).toBeNull();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('does not re-prompt a driver who already said no for good', async () => {
    (Notifications.getPermissionsAsync as jest.Mock).mockResolvedValue({
      granted: false,
      canAskAgain: false,
    });

    expect(await registerPushToken()).toBeNull();
    expect(Notifications.requestPermissionsAsync).not.toHaveBeenCalled();
  });

  it('degrades instead of crashing when the EAS project id is missing', async () => {
    // `npm start` without `eas init`. Expo cannot mint a token, and a throw
    // here would take down the sign-in that triggered it.
    (Constants as any).expoConfig = { extra: {} };
    (Constants as any).easConfig = null;

    expect(await registerPushToken()).toBeNull();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('swallows a failure to mint a token', async () => {
    // Simulators have no push token at all.
    (Notifications.getExpoPushTokenAsync as jest.Mock).mockRejectedValue(
      new Error('no push token on simulator'),
    );

    await expect(registerPushToken()).resolves.toBeNull();
  });

  it('swallows a backend that is down', async () => {
    mockFetch.mockRejectedValue(new Error('network'));
    await expect(registerPushToken()).resolves.toBeNull();
  });
});

describe('unregisterPushToken', () => {
  it('deletes exactly the token this device registered', async () => {
    await registerPushToken();
    mockFetch.mockClear();

    await unregisterPushToken();

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/me/push-token',
      expect.objectContaining({ method: 'DELETE' }),
    );
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
    expect(body.token).toBe('ExponentPushToken[test]');
  });

  it('does nothing when this device never registered', async () => {
    await unregisterPushToken();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('clears the stored token even when the backend call fails', async () => {
    // Otherwise a failed sign-out leaves a stale token that the next
    // unregister would keep trying to delete forever.
    await registerPushToken();
    mockFetch.mockRejectedValue(new Error('network'));

    await unregisterPushToken();
    mockFetch.mockClear();
    mockFetch.mockResolvedValue({} as never);

    await unregisterPushToken();
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
