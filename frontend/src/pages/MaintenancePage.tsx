import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ServiceReminders } from '@/components/maintenance/ServiceReminders';
import { MaintenanceHistory } from '@/components/maintenance/MaintenanceHistory';
import { FuelTracking } from '@/components/maintenance/FuelTracking';
import { DriverRequests } from '@/components/maintenance/DriverRequests';
import { Wrench, History, Fuel, MessageSquareWarning } from 'lucide-react';
import { driverDataApi } from '@/lib/driverData';

export default function MaintenancePage() {
  const [activeTab, setActiveTab] = useState('reminders');

  // Lightweight count for the tab badge (open driver-reported issues).
  const { data: openRequests = 0 } = useQuery({
    queryKey: ['maintenance-requests', 'open-count'],
    queryFn: async () => (await driverDataApi.maintenanceRequests('open')).length,
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Maintenance & Fuel</h1>
        <p className="text-muted-foreground mt-1">
          Track service intervals, log maintenance, and monitor fuel consumption
        </p>
      </div>
      
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-4 lg:w-[680px]">
          <TabsTrigger value="reminders" className="flex items-center gap-2">
            <Wrench className="h-4 w-4" />
            <span className="hidden sm:inline">Service Reminders</span>
            <span className="sm:hidden">Reminders</span>
          </TabsTrigger>
          <TabsTrigger value="history" className="flex items-center gap-2">
            <History className="h-4 w-4" />
            <span className="hidden sm:inline">Maintenance Log</span>
            <span className="sm:hidden">History</span>
          </TabsTrigger>
          <TabsTrigger value="fuel" className="flex items-center gap-2">
            <Fuel className="h-4 w-4" />
            <span className="hidden sm:inline">Fuel Tracking</span>
            <span className="sm:hidden">Fuel</span>
          </TabsTrigger>
          <TabsTrigger value="requests" className="flex items-center gap-2">
            <MessageSquareWarning className="h-4 w-4" />
            <span className="hidden sm:inline">Driver Requests</span>
            <span className="sm:hidden">Requests</span>
            {openRequests > 0 && (
              <span className="ml-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1.5 text-xs font-semibold text-destructive-foreground">
                {openRequests}
              </span>
            )}
          </TabsTrigger>
        </TabsList>
        
        <TabsContent value="reminders" className="mt-6">
          <ServiceReminders />
        </TabsContent>
        
        <TabsContent value="history" className="mt-6">
          <MaintenanceHistory />
        </TabsContent>
        
        <TabsContent value="fuel" className="mt-6">
          <FuelTracking />
        </TabsContent>

        <TabsContent value="requests" className="mt-6">
          <DriverRequests />
        </TabsContent>
      </Tabs>
    </div>
  );
}
