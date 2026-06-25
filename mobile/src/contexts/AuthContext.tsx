import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { getToken } from '../lib/auth';
import { signIn as apiSignIn, signOut as apiSignOut } from '../lib/authApi';

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
    });
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    await apiSignIn(email, password);
    setIsAuthenticated(true);
  }, []);

  const signOut = useCallback(async () => {
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
