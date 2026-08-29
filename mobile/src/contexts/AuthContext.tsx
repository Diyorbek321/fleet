import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { getToken } from '../lib/auth';
import { signIn as apiSignIn, signOut as apiSignOut } from '../lib/authApi';
import { registerPushToken, unregisterPushToken } from '../lib/push';

interface AuthState {
  isAuthenticated: boolean;
  /** True while we check storage for an existing session at startup. */
  initializing: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    getToken().then((token) => {
      setIsAuthenticated(!!token);
      setInitializing(false);
      // Re-register on every launch with a live session, not just at sign-in:
      // Expo push tokens rotate on reinstall and on restore to a new handset,
      // and a driver who stays signed in for months would otherwise keep a
      // token the backend can no longer deliver to.
      if (token) void registerPushToken();
    });
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    await apiSignIn(email, password);
    setIsAuthenticated(true);
    // Deliberately not awaited: registration needs a permission prompt and a
    // network round trip, and neither should stand between a driver and the
    // app they just signed in to.
    void registerPushToken();
  }, []);

  const signOut = useCallback(async () => {
    // Before apiSignOut, which clears the stored access token — the DELETE is
    // an authenticated call, so afterwards it could not be made at all.
    await unregisterPushToken();
    await apiSignOut();
    setIsAuthenticated(false);
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, initializing, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
