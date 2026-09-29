import React from 'react';
import { Platform } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { palette, shadow } from '../theme/theme';
import { HomeScreen } from '../screens/HomeScreen';
import { TripsScreen } from '../screens/TripsScreen';
import { QueueScreen } from '../screens/QueueScreen';
import { FuelScreen } from '../screens/FuelScreen';
import { ExpensesScreen } from '../screens/ExpensesScreen';
import { MaintenanceScreen } from '../screens/MaintenanceScreen';
import { ProfileScreen } from '../screens/ProfileScreen';

const Tab = createBottomTabNavigator();

/** Filled icon when focused, outline when not — a subtle but legible active cue. */
const ICONS: Record<string, [keyof typeof Ionicons.glyphMap, keyof typeof Ionicons.glyphMap]> = {
  Home: ['home', 'home-outline'],
  Trips: ['cube', 'cube-outline'],
  Queue: ['time', 'time-outline'],
  Fuel: ['speedometer', 'speedometer-outline'],
  Expenses: ['wallet', 'wallet-outline'],
  Maintenance: ['construct', 'construct-outline'],
  Profile: ['person', 'person-outline'],
};

export function Tabs() {
  const { t } = useTranslation();
  // Android 16 draws every app edge-to-edge: without the bottom inset the tab
  // bar sits under the system navigation buttons.
  const insets = useSafeAreaInsets();
  const baseHeight = Platform.OS === 'ios' ? 86 - insets.bottom : 66;

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: palette.brand,
        tabBarInactiveTintColor: palette.faint,
        tabBarLabelStyle: { fontSize: 11, fontWeight: '700', marginBottom: 4 },
        tabBarStyle: {
          backgroundColor: palette.surface,
          borderTopWidth: 0,
          height: Math.max(baseHeight, 58) + insets.bottom,
          paddingTop: 8,
          paddingBottom: insets.bottom,
          ...shadow.lg,
        },
        tabBarIcon: ({ color, size, focused }) => {
          const [active, inactive] = ICONS[route.name] ?? ['ellipse', 'ellipse-outline'];
          return <Ionicons name={focused ? active : inactive} color={color} size={size} />;
        },
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={{ title: t('tabs.home') }} />
      <Tab.Screen name="Trips" component={TripsScreen} options={{ tabBarLabel: t('tabs.trips') }} />
      <Tab.Screen name="Queue" component={QueueScreen} options={{ tabBarLabel: t('tabs.queue') }} />
      <Tab.Screen name="Fuel" component={FuelScreen} options={{ tabBarLabel: t('tabs.fuel') }} />
      <Tab.Screen
        name="Expenses"
        component={ExpensesScreen}
        options={{ tabBarLabel: t('tabs.expenses') }}
      />
      <Tab.Screen
        name="Maintenance"
        component={MaintenanceScreen}
        options={{ tabBarLabel: t('tabs.maintenance') }}
      />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{ tabBarLabel: t('tabs.profile') }}
      />
    </Tab.Navigator>
  );
}
