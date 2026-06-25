import React, { useState } from 'react';
import { useMaintenance } from '@/contexts/MaintenanceContext';
import { useTrucks } from '@/contexts/TruckContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AlertTriangle, Clock, CheckCircle, Wrench } from 'lucide-react';
import { format, differenceInDays } from 'date-fns';
import { ServiceType } from '@/types';
import { LogServiceModal } from './LogServiceModal';

const serviceTypeLabels: Record<ServiceType, string> = {
  oil_change: 'Oil Change',
  tire_rotation: 'Tire Rotation',
  brake_inspection: 'Brake Inspection',
  engine_service: 'Engine Service',
  transmission: 'Transmission',
  other: 'Other',
};

const serviceTypeIcons: Record<ServiceType, string> = {
  oil_change: '🛢️',
  tire_rotation: '🔄',
  brake_inspection: '🛑',
  engine_service: '⚙️',
  transmission: '🔧',
  other: '📋',
};

export function ServiceReminders() {
  const { getOverdueServices, getUpcomingServices, serviceIntervals } = useMaintenance();
  const { trucks } = useTrucks();
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [selectedInterval, setSelectedInterval] = useState<string | null>(null);
  
  const overdueServices = getOverdueServices();
  const upcomingServices = getUpcomingServices(30);
  
  const getTruckName = (truckId: string) => {
    const truck = trucks.find(t => t.id === truckId);
    return truck ? `${truck.name} (${truck.plateNumber})` : truckId;
  };
  
  const handleLogService = (intervalId: string) => {
    setSelectedInterval(intervalId);
    setLogModalOpen(true);
  };
  
  return (
    <div className="space-y-6">
      {/* Overdue Services */}
      {overdueServices.length > 0 && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              <CardTitle className="text-destructive">Overdue Services</CardTitle>
            </div>
            <CardDescription>These services are past their scheduled date</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {overdueServices.map(interval => {
                const daysOverdue = differenceInDays(new Date(), new Date(interval.nextServiceDate));
                return (
                  <div
                    key={interval.id}
                    className="flex items-center justify-between p-3 rounded-lg bg-background border border-destructive/20"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{serviceTypeIcons[interval.serviceType]}</span>
                      <div>
                        <p className="font-medium text-foreground">
                          {serviceTypeLabels[interval.serviceType]}
                        </p>
                        <p className="text-sm text-muted-foreground">{getTruckName(interval.truckId)}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge variant="destructive">{daysOverdue} days overdue</Badge>
                      <Button size="sm" onClick={() => handleLogService(interval.id)}>
                        Log Service
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
      
      {/* Upcoming Services */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Clock className="h-5 w-5 text-primary" />
            <CardTitle>Upcoming Services</CardTitle>
          </div>
          <CardDescription>Services due in the next 30 days</CardDescription>
        </CardHeader>
        <CardContent>
          {upcomingServices.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <CheckCircle className="h-12 w-12 text-status-moving mb-3" />
              <p className="text-muted-foreground">No upcoming services in the next 30 days</p>
            </div>
          ) : (
            <div className="space-y-3">
              {upcomingServices.map(interval => {
                const daysUntil = differenceInDays(new Date(interval.nextServiceDate), new Date());
                const urgency = daysUntil <= 7 ? 'warning' : 'default';
                
                return (
                  <div
                    key={interval.id}
                    className="flex items-center justify-between p-3 rounded-lg bg-muted/50 border border-border"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{serviceTypeIcons[interval.serviceType]}</span>
                      <div>
                        <p className="font-medium text-foreground">
                          {serviceTypeLabels[interval.serviceType]}
                        </p>
                        <p className="text-sm text-muted-foreground">{getTruckName(interval.truckId)}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="text-right">
                        <Badge variant={urgency === 'warning' ? 'secondary' : 'outline'}>
                          {daysUntil === 0 ? 'Today' : `${daysUntil} days`}
                        </Badge>
                        <p className="text-xs text-muted-foreground mt-1">
                          {format(new Date(interval.nextServiceDate), 'MMM d, yyyy')}
                        </p>
                      </div>
                      <Button size="sm" variant="outline" onClick={() => handleLogService(interval.id)}>
                        Log Service
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
      
      {/* All Service Intervals Summary */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Wrench className="h-5 w-5 text-muted-foreground" />
            <CardTitle>Service Interval Summary</CardTitle>
          </div>
          <CardDescription>Overview of all configured service intervals</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(
              serviceIntervals.reduce((acc, interval) => {
                const key = interval.serviceType;
                if (!acc[key]) acc[key] = { total: 0, overdue: 0, upcoming: 0 };
                acc[key].total++;
                
                const daysUntil = differenceInDays(new Date(interval.nextServiceDate), new Date());
                if (daysUntil < 0) acc[key].overdue++;
                else if (daysUntil <= 30) acc[key].upcoming++;
                
                return acc;
              }, {} as Record<string, { total: number; overdue: number; upcoming: number }>)
            ).map(([type, stats]) => (
              <div key={type} className="p-4 rounded-lg bg-muted/30 border border-border">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">{serviceTypeIcons[type as ServiceType]}</span>
                  <h4 className="font-medium">{serviceTypeLabels[type as ServiceType]}</h4>
                </div>
                <div className="flex gap-3 text-sm">
                  <span className="text-muted-foreground">{stats.total} total</span>
                  {stats.overdue > 0 && (
                    <span className="text-destructive">{stats.overdue} overdue</span>
                  )}
                  {stats.upcoming > 0 && (
                    <span className="text-primary">{stats.upcoming} upcoming</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      
      <LogServiceModal
        open={logModalOpen}
        onOpenChange={setLogModalOpen}
        intervalId={selectedInterval}
      />
    </div>
  );
}
