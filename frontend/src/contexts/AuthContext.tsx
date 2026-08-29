import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { authApi, tokenStorage, ApiError, type AuthUser } from '@/lib/api';

interface AuthContextType {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** Resolves with the signed-in user so callers can route by role without waiting for state. */
  login: (email: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  /** Change your own password. Signs out every other device. */
  changePassword: (current: string, next: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Restore session on mount
  useEffect(() => {
    const access = tokenStorage.getAccess();
    if (!access) {
      setIsLoading(false);
      return;
    }
    authApi
      .me()
      .then(setUser)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          tokenStorage.clear();
        }
      })
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await authApi.login(email, password);
    tokenStorage.set(tokens.access_token, tokens.refresh_token);
    const me = await authApi.me();
    setUser(me);
    return me;
  }, []);

  const changePassword = useCallback(async (current: string, next: string) => {
    const tokens = await authApi.changePassword(current, next);
    // The server invalidates every token minted under the old password,
    // including the one that made this very request, and hands back a
    // replacement pair. Storing them is what keeps the caller signed in —
    // skip this and the next request 401s and the user is thrown to the login
    // screen for having changed their password.
    tokenStorage.set(tokens.access_token, tokens.refresh_token);
    setUser(await authApi.me());
  }, []);

  const logout = useCallback(async () => {
    const refresh = tokenStorage.getRefresh();
    if (refresh) {
      await authApi.logout(refresh).catch(() => {
        /* revoke failures shouldn't block logout */
      });
    }
    tokenStorage.clear();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
        changePassword,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
