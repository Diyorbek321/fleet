import React, { useEffect, useState } from 'react';
import { ActivityIndicator, SafeAreaView, StyleSheet } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { initI18n } from './src/i18n';
import { AuthProvider, useAuth } from './src/contexts/AuthContext';
import { LoginScreen } from './src/screens/LoginScreen';
import { Tabs } from './src/navigation/Tabs';
// Side-effect import: registers the background location task with TaskManager
// at module load so the OS can invoke it even when the UI isn't mounted.
import './src/lib/location-task';

export default function App() {
  const [i18nReady, setI18nReady] = useState(false);

  useEffect(() => {
    initI18n().then(() => setI18nReady(true));
  }, []);

  if (!i18nReady) return <Splash />;

  return (
    <SafeAreaProvider>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
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
