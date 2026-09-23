import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMaintenance } from '@/contexts/MaintenanceContext';
import { useTrucks } from '@/contexts/TruckContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AlertTriangle, Clock, CheckCircle, Wrench } from 'lucide-react';
import { format, differenceInDays } from '@/lib/datetime';
import { ServiceType } from '@/types';
import { LogServiceModal } from './LogServiceModal';


const serviceTypeIcons: Record<ServiceType, string> = {
  oil_change: '🛢️',
  tire_rotation: '🔄',
  brake_inspection: '🛑',
  engine_service: '⚙️',
  transmission: '🔧',
  other: '📋',
};

export function ServiceReminders() {
  const { t } = useTranslation();
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
              <CardTitle className="text-destructive">{t('maintenance.reminders.overdueTitle')}</CardTitle>
            </div>
            <CardDescription>{t('maintenance.reminders.overdueDescription')}</CardDescription>
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
                          {t(`maintenance.serviceTypes.${interval.serviceType}`)}
                        </p>
                        <p className="text-sm text-muted-foreground">{getTruckName(interval.truckId)}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge variant="destructive">{t('maintenance.reminders.daysOverdue', { count: daysOverdue })}</Badge>
                      <Button size="sm" onClick={() => handleLogService(interval.id)}>
                        {t('maintenance.reminders.logService')}
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
            <CardTitle>{t('maintenance.reminders.upcomingTitle')}</CardTitle>
          </div>
          <CardDescription>{t('maintenance.reminders.upcomingDescription')}</CardDescription>
        </CardHeader>
        <CardContent>
          {upcomingServices.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <CheckCircle className="h-12 w-12 text-status-moving mb-3" />
              <p className="text-muted-foreground">{t('maintenance.reminders.noUpcoming')}</p>
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
                          {t(`maintenance.serviceTypes.${interval.serviceType}`)}
                        </p>
                        <p className="text-sm text-muted-foreground">{getTruckName(interval.truckId)}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="text-right">
                        <Badge variant={urgency === 'warning' ? 'secondary' : 'outline'}>
                          {daysUntil === 0
                            ? t('common.today')
                            : t('maintenance.reminders.inDays', { count: daysUntil })}
                        </Badge>
                        <p className="text-xs text-muted-foreground mt-1">
                          {format(new Date(interval.nextServiceDate), 'MMM d, yyyy')}
                        </p>
                      </div>
                      <Button size="sm" variant="outline" onClick={() => handleLogService(interval.id)}>
                        {t('maintenance.reminders.logService')}
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
            <CardTitle>{t('maintenance.reminders.summaryTitle')}</CardTitle>
          </div>
          <CardDescription>{t('maintenance.reminders.summaryDescription')}</CardDescription>
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
                  <h4 className="font-medium">{t(`maintenance.serviceTypes.${type}`)}</h4>
                </div>
                <div className="flex gap-3 text-sm">
                  <span className="text-muted-foreground">
                    {t('maintenance.reminders.statTotal', { count: stats.total })}
                  </span>
                  {stats.overdue > 0 && (
                    <span className="text-destructive">
                      {t('maintenance.reminders.statOverdue', { count: stats.overdue })}
                    </span>
                  )}
                  {stats.upcoming > 0 && (
                    <span className="text-primary">
                      {t('maintenance.reminders.statUpcoming', { count: stats.upcoming })}
                    </span>
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
