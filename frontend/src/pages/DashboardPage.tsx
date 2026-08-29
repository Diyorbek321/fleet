import React from 'react';
import { useTranslation } from 'react-i18next';
import { StatsCards } from '@/components/dashboard/StatsCards';
import { RecentActivity } from '@/components/dashboard/RecentActivity';
import { FleetOverviewChart } from '@/components/dashboard/FleetOverviewChart';
import { FuelCostWidget } from '@/components/dashboard/FuelCostWidget';

export default function DashboardPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('dashboard.title')}</h1>
        <p className="text-muted-foreground">{t('dashboard.subtitle')}</p>
      </div>

      {/* Stats Cards */}
      <StatsCards />

      {/* Fuel & Efficiency */}
      <FuelCostWidget />

      {/* Charts and Activity */}
      <div className="grid gap-6 lg:grid-cols-7">
        <div className="lg:col-span-4">
          <FleetOverviewChart />
        </div>
        <div className="lg:col-span-3">
          <RecentActivity />
        </div>
      </div>
    </div>
  );
}
