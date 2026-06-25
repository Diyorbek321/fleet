import React, { useState } from 'react';
import { useMaintenance } from '@/contexts/MaintenanceContext';
import { useTrucks } from '@/contexts/TruckContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Plus, Search, Filter } from 'lucide-react';
import { format } from 'date-fns';
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

const serviceTypeBadgeColors: Record<ServiceType, string> = {
  oil_change: 'bg-amber-500/20 text-amber-500',
  tire_rotation: 'bg-blue-500/20 text-blue-500',
  brake_inspection: 'bg-red-500/20 text-red-500',
  engine_service: 'bg-purple-500/20 text-purple-500',
  transmission: 'bg-green-500/20 text-green-500',
  other: 'bg-gray-500/20 text-gray-500',
};

export function MaintenanceHistory() {
  const { maintenanceRecords } = useMaintenance();
  const { trucks } = useTrucks();
  
  const [searchQuery, setSearchQuery] = useState('');
  const [filterTruck, setFilterTruck] = useState<string>('all');
  const [filterService, setFilterService] = useState<string>('all');
  const [logModalOpen, setLogModalOpen] = useState(false);
  
  const getTruckName = (truckId: string) => {
    const truck = trucks.find(t => t.id === truckId);
    return truck ? `${truck.name}` : truckId;
  };
  
  const getTruckPlate = (truckId: string) => {
    const truck = trucks.find(t => t.id === truckId);
    return truck?.plateNumber || '';
  };
  
  const filteredRecords = maintenanceRecords.filter(record => {
    const matchesSearch = 
      getTruckName(record.truckId).toLowerCase().includes(searchQuery.toLowerCase()) ||
      getTruckPlate(record.truckId).toLowerCase().includes(searchQuery.toLowerCase()) ||
      (record.vendor?.toLowerCase().includes(searchQuery.toLowerCase()));
    
    const matchesTruck = filterTruck === 'all' || record.truckId === filterTruck;
    const matchesService = filterService === 'all' || record.serviceType === filterService;
    
    return matchesSearch && matchesTruck && matchesService;
  });
  
  const totalCost = filteredRecords.reduce((sum, r) => sum + r.cost, 0);
  
  return (
    <div className="space-y-6">
      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="pt-6">
            <div className="text-2xl font-bold text-foreground">{maintenanceRecords.length}</div>
            <p className="text-sm text-muted-foreground">Total Records</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-2xl font-bold text-foreground">
              ${totalCost.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
            <p className="text-sm text-muted-foreground">Total Spent (filtered)</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-2xl font-bold text-foreground">
              ${filteredRecords.length > 0 ? (totalCost / filteredRecords.length).toFixed(2) : '0.00'}
            </div>
            <p className="text-sm text-muted-foreground">Avg. per Service</p>
          </CardContent>
        </Card>
      </div>
      
      {/* Filters and Actions */}
      <Card>
        <CardHeader className="pb-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <CardTitle>Maintenance Log</CardTitle>
              <CardDescription>Complete history of all maintenance services</CardDescription>
            </div>
            <Button onClick={() => setLogModalOpen(true)} className="w-full sm:w-auto">
              <Plus className="h-4 w-4 mr-2" />
              Log Service
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by truck or vendor..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select value={filterTruck} onValueChange={setFilterTruck}>
              <SelectTrigger className="w-full sm:w-[180px]">
                <Filter className="h-4 w-4 mr-2" />
                <SelectValue placeholder="Filter truck" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Trucks</SelectItem>
                {trucks.map(truck => (
                  <SelectItem key={truck.id} value={truck.id}>
                    {truck.plateNumber}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={filterService} onValueChange={setFilterService}>
              <SelectTrigger className="w-full sm:w-[180px]">
                <SelectValue placeholder="Filter service" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Services</SelectItem>
                {Object.entries(serviceTypeLabels).map(([value, label]) => (
                  <SelectItem key={value} value={value}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          
          <div className="rounded-md border border-border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead>Date</TableHead>
                  <TableHead>Truck</TableHead>
                  <TableHead>Service</TableHead>
                  <TableHead className="text-right">Mileage</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="hidden md:table-cell">Vendor</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredRecords.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                      No maintenance records found
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredRecords.map(record => (
                    <TableRow key={record.id}>
                      <TableCell className="font-medium">
                        {format(new Date(record.date), 'MMM d, yyyy')}
                      </TableCell>
                      <TableCell>
                        <div>
                          <span className="font-medium">{getTruckName(record.truckId)}</span>
                          <span className="text-muted-foreground text-sm ml-2">
                            {getTruckPlate(record.truckId)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge className={serviceTypeBadgeColors[record.serviceType]} variant="secondary">
                          {serviceTypeLabels[record.serviceType]}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {record.mileage.toLocaleString()} mi
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        ${record.cost.toFixed(2)}
                      </TableCell>
                      <TableCell className="hidden md:table-cell text-muted-foreground">
                        {record.vendor || '-'}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
      
      <LogServiceModal open={logModalOpen} onOpenChange={setLogModalOpen} />
    </div>
  );
}
