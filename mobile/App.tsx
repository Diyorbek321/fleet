import React, { useEffect, useState } from 'react';
import { ActivityIndicator, SafeAreaView, StyleSheet } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { initI18n } from './src/i18n';
import { AuthProvider, useAuth } from './src/contexts/AuthContext';
import { LoginScreen } from './src/screens/LoginScreen';
import { Tabs } from './src/navigation/Tabs';
import { UpdateGate } from './src/components/UpdateGate';
// Side-effect import: registers the background location task with TaskManager
// at module load so the OS can invoke it even when the UI isn't mounted.
import './src/lib/location-task';
// Likewise the task that restarts tracking on the server's wake-up push.
import './src/lib/wake-task';

export default function App() {
  const [i18nReady, setI18nReady] = useState(false);

  useEffect(() => {
    initI18n().then(() => setI18nReady(true));
  }, []);

  if (!i18nReady) return <Splash />;

  return (
    <SafeAreaProvider>
      <UpdateGate>
        <AuthProvider>
          <AppContent />
        </AuthProvider>
      </UpdateGate>
    </SafeAreaProvider>
  );
}

/** Auth gate: login screen when signed out, the tab navigator when signed in. */
function AppContent() {
  const { isAuthenticated, initializing } = useAuth();

  if (initializing) return <Splash />;
  if (!isAuthenticated) return <LoginScreen />;

  return (
    <NavigationContainer>
      <StatusBar style="light" />
      <Tabs />
    </NavigationContainer>
  );
}

function Splash() {
  return (
    <SafeAreaView style={styles.center}>
      <ActivityIndicator size="large" color="#2563eb" />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#f8fafc' },
});
