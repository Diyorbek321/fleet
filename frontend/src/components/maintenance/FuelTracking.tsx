import React, { useState } from 'react';
import { useMaintenance } from '@/contexts/MaintenanceContext';
import { useTrucks } from '@/contexts/TruckContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Plus, Fuel, TrendingUp, DollarSign, Gauge } from 'lucide-react';
import { format } from 'date-fns';
import { AddFuelLogModal } from './AddFuelLogModal';

export function FuelTracking() {
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
            <SelectValue placeholder="Select truck" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Trucks</SelectItem>
            {trucks.filter(t => t.isEnabled).map(truck => (
              <SelectItem key={truck.id} value={truck.id}>
                {truck.name} ({truck.plateNumber})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        
        <Button onClick={() => setAddModalOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add Fuel Entry
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
                <p className="text-sm text-muted-foreground">Total Gallons</p>
                <p className="text-2xl font-bold text-foreground">{stats.totalGallons.toLocaleString()}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-status-stopped/10">
                <DollarSign className="h-5 w-5 text-status-stopped" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Spent</p>
                <p className="text-2xl font-bold text-foreground">
                  ${stats.totalCost.toLocaleString(undefined, { minimumFractionDigits: 2 })}
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
                <p className="text-sm text-muted-foreground">Avg. MPG</p>
                <p className="text-2xl font-bold text-foreground">{stats.avgMpg}</p>
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
                <p className="text-sm text-muted-foreground">Avg. Price/Gal</p>
                <p className="text-2xl font-bold text-foreground">${stats.avgPricePerGallon}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Fuel Log Table */}
      <Card>
        <CardHeader>
          <CardTitle>Fuel Purchase Log</CardTitle>
          <CardDescription>
            {selectedTruck === 'all' 
              ? 'Showing all fuel entries' 
              : `Showing entries for ${getTruckName(selectedTruck)}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border border-border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead>Date</TableHead>
                  {selectedTruck === 'all' && <TableHead>Truck</TableHead>}
                  <TableHead className="text-right">Gallons</TableHead>
                  <TableHead className="text-right">Price/Gal</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="text-right">Mileage</TableHead>
                  <TableHead className="hidden md:table-cell">Location</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayedLogs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={selectedTruck === 'all' ? 7 : 6} className="text-center py-8 text-muted-foreground">
                      No fuel entries found
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
                      <TableCell className="text-right">{log.gallons}</TableCell>
                      <TableCell className="text-right">${log.pricePerGallon.toFixed(2)}</TableCell>
                      <TableCell className="text-right font-medium">${log.totalCost.toFixed(2)}</TableCell>
                      <TableCell className="text-right">{log.mileage.toLocaleString()}</TableCell>
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
