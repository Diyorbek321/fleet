import AsyncStorage from '@react-native-async-storage/async-storage';

const TOKEN_KEY = 'fleet_driver_token';
const REFRESH_KEY = 'fleet_driver_refresh';

async function read(key: string): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(key);
  } catch {
    return null;
  }
}

async function write(key: string, value: string | null): Promise<void> {
  try {
    if (value) await AsyncStorage.setItem(key, value);
    else await AsyncStorage.removeItem(key);
  } catch {
    // Non-fatal: value simply won't persist across launches.
  }
}

/** The stored JWT access token, or null. */
export const getToken = () => read(TOKEN_KEY);
export const setToken = (token: string | null) => write(TOKEN_KEY, token);

/** The stored refresh token, or null. */
export const getRefreshToken = () => read(REFRESH_KEY);
export const setRefreshToken = (token: string | null) => write(REFRESH_KEY, token);

/** Clear both tokens (sign out). */
export async function clearTokens(): Promise<void> {
  await setToken(null);
  await setRefreshToken(null);
}
