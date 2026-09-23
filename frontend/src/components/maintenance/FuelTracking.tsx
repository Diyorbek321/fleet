import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMaintenance } from '@/contexts/MaintenanceContext';
import { useTrucks } from '@/contexts/TruckContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Plus, Fuel, TrendingUp, Banknote, Gauge } from 'lucide-react';
import { format } from '@/lib/datetime';
import { AddFuelLogModal } from './AddFuelLogModal';
import { formatAmount, formatKm, formatL100km, formatLiters } from '@/lib/format';

export function FuelTracking() {
  const { t } = useTranslation();
  const { fuelLogs, calculateFuelStats, getFuelLogsByTruck } = useMaintenance();
  const { trucks } = useTrucks();
  
  const [selectedTruck, setSelectedTruck] = useState<string>('all');
  const [addModalOpen, setAddModalOpen] = useState(false);
  
  const stats = calculateFuelStats(selectedTruck === 'all' ? undefined : selectedTruck);
  const displayedLogs = selectedTruck === 'all' 
    ? fuelLogs 
    : getFuelLogsByTruck(selectedTruck);
  
  const getTruckName = (truckId: string) => {
    const truck = trucks.find(t => t.id === truckId);
    return truck ? `${truck.name}` : truckId;
  };
  
  const getTruckPlate = (truckId: string) => {
    const truck = trucks.find(t => t.id === truckId);
    return truck?.plateNumber || '';
  };
  
  return (
    <div className="space-y-6">
      {/* Truck Selector */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <Select value={selectedTruck} onValueChange={setSelectedTruck}>
          <SelectTrigger className="w-full sm:w-[250px]">
            <SelectValue placeholder={t('maintenance.fuel.selectTruck')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('maintenance.fuel.allTrucks')}</SelectItem>
            {trucks.filter(t => t.isEnabled).map(truck => (
              <SelectItem key={truck.id} value={truck.id}>
                {truck.name} ({truck.plateNumber})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        
        <Button onClick={() => setAddModalOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          {t('maintenance.fuel.addEntry')}
        </Button>
      </div>
      
      {/* Stats Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10">
                <Fuel className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">{t('maintenance.fuel.totalLitres')}</p>
                <p className="text-2xl font-bold text-foreground">{formatLiters(stats.totalGallons)} {t('common.liters')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-status-stopped/10">
                <Banknote className="h-5 w-5 text-status-stopped" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">{t('maintenance.fuel.totalSpent')}</p>
                <p className="text-2xl font-bold text-foreground">
                  {formatAmount(stats.totalCost)} {t('common.currency')}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-status-moving/10">
                <Gauge className="h-5 w-5 text-status-moving" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">{t('maintenance.fuel.avgConsumption')}</p>
                <p className="text-2xl font-bold text-foreground">{formatL100km(stats.avgMpg)} {t('common.lPer100km')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-amber-500/10">
                <TrendingUp className="h-5 w-5 text-amber-500" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">{t('maintenance.fuel.avgPrice')}</p>
                <p className="text-2xl font-bold text-foreground">{formatAmount(stats.avgPricePerGallon)} {t('common.currency')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Fuel Log Table */}
      <Card>
        <CardHeader>
          <CardTitle>{t('maintenance.fuel.logTitle')}</CardTitle>
          <CardDescription>
            {selectedTruck === 'all'
              ? t('maintenance.fuel.allEntries')
              : t('maintenance.fuel.entriesFor', { truck: getTruckName(selectedTruck) })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border border-border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead>{t('maintenance.fuel.colDate')}</TableHead>
                  {selectedTruck === 'all' && <TableHead>{t('maintenance.fuel.colTruck')}</TableHead>}
                  <TableHead className="text-right">{t('maintenance.fuel.colLitres')}</TableHead>
                  <TableHead className="text-right">{t('maintenance.fuel.colPricePerL')}</TableHead>
                  <TableHead className="text-right">{t('maintenance.fuel.colTotal')}</TableHead>
                  <TableHead className="text-right">{t('maintenance.fuel.colOdometer')}</TableHead>
                  <TableHead className="hidden md:table-cell">{t('maintenance.fuel.colLocation')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayedLogs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={selectedTruck === 'all' ? 7 : 6} className="text-center py-8 text-muted-foreground">
                      {t('maintenance.fuel.empty')}
                    </TableCell>
                  </TableRow>
                ) : (
                  displayedLogs.slice(0, 20).map(log => (
                    <TableRow key={log.id}>
                      <TableCell className="font-medium">
                        {format(new Date(log.date), 'MMM d, yyyy')}
                      </TableCell>
                      {selectedTruck === 'all' && (
                        <TableCell>
                          <div>
                            <span className="font-medium">{getTruckName(log.truckId)}</span>
                            <span className="text-muted-foreground text-sm ml-2">
                              {getTruckPlate(log.truckId)}
                            </span>
                          </div>
                        </TableCell>
                      )}
                      <TableCell className="text-right">{formatLiters(log.gallons, 1)} {t('common.liters')}</TableCell>
                      <TableCell className="text-right">{formatAmount(log.pricePerGallon)} {t('common.currency')}</TableCell>
                      <TableCell className="text-right font-medium">{formatAmount(log.totalCost)} {t('common.currency')}</TableCell>
                      <TableCell className="text-right">{formatKm(log.mileage)} {t('common.km')}</TableCell>
                      <TableCell className="hidden md:table-cell text-muted-foreground">
                        {log.location || '-'}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
      
      <AddFuelLogModal open={addModalOpen} onOpenChange={setAddModalOpen} />
    </div>
  );
}
