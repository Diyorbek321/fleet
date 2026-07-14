import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Search, Filter, MapPin, Clock, MoreHorizontal, Pencil, Power, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent } from '@/components/ui/card';
import { useTrucks } from '@/contexts/TruckContext';
import { TruckFormModal } from '@/components/trucks/TruckFormModal';
import { Truck, TruckStatus } from '@/types';
import { cn } from '@/lib/utils';
import { formatDistanceToNow } from 'date-fns';

export default function TrucksPage() {
  const { trucks, isLoading, setSelectedTruck, toggleTruckEnabled, removeTruck } = useTrucks();
  const navigate = useNavigate();
  
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<TruckStatus | 'all'>('all');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingTruck, setEditingTruck] = useState<Truck | null>(null);

  const filteredTrucks = useMemo(() => {
    return trucks.filter((truck) => {
      const matchesSearch =
        truck.plateNumber.toLowerCase().includes(searchQuery.toLowerCase()) ||
        truck.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        truck.driverName?.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesStatus = statusFilter === 'all' || truck.status === statusFilter;

      return matchesSearch && matchesStatus;
    });
  }, [trucks, searchQuery, statusFilter]);

  const statusBadgeClasses = {
    moving: 'bg-status-moving/20 text-status-moving border-status-moving/30',
    stopped: 'bg-status-stopped/20 text-status-stopped border-status-stopped/30',
    offline: 'bg-status-offline/20 text-status-offline border-status-offline/30',
  };

  const handleTruckClick = (truck: Truck) => {
    navigate(`/trucks/${truck.id}`);
  };

  const handleViewOnMap = (truck: Truck) => {
    setSelectedTruck(truck);
    navigate('/map');
  };

  const handleEdit = (truck: Truck) => {
    setEditingTruck(truck);
    setIsModalOpen(true);
  };

  const handleAddNew = () => {
    setEditingTruck(null);
    setIsModalOpen(true);
  };

  const handleDelete = (truck: Truck) => {
    if (window.confirm(`Delete ${truck.name} (${truck.plateNumber})? This cannot be undone.`)) {
      removeTruck(truck.id);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div className="skeleton h-8 w-32" />
          <div className="skeleton h-10 w-32" />
        </div>
        <Card className="border-border/50 bg-card">
          <CardContent className="p-0">
            <div className="space-y-4 p-6">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="skeleton h-16 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Trucks</h1>
          <p className="text-muted-foreground">
            Manage your fleet vehicles and tracking devices
          </p>
        </div>
        <Button onClick={handleAddNew} className="bg-primary hover:bg-primary/90">
          <Plus className="mr-2 h-4 w-4" />
          Add New Truck
        </Button>
      </div>

      {/* Filters */}
      <Card className="border-border/50 bg-card">
        <CardContent className="p-4">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search trucks, plates, drivers..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 bg-secondary/50 border-0"
              />
            </div>
            <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as TruckStatus | 'all')}>
              <SelectTrigger className="w-full sm:w-40 bg-secondary/50 border-0">
                <Filter className="mr-2 h-4 w-4" />
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent className="bg-popover">
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="moving">Moving</SelectItem>
                <SelectItem value="stopped">Stopped</SelectItem>
                <SelectItem value="offline">Offline</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card className="border-border/50 bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-border/50 hover:bg-transparent">
                <TableHead className="text-muted-foreground">Truck</TableHead>
                <TableHead className="text-muted-foreground">Driver</TableHead>
                <TableHead className="text-muted-foreground">Status</TableHead>
                <TableHead className="text-muted-foreground">Speed</TableHead>
                <TableHead className="text-muted-foreground hidden md:table-cell">Location</TableHead>
                <TableHead className="text-muted-foreground">Last Update</TableHead>
                <TableHead className="text-muted-foreground w-12"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredTrucks.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    No trucks found matching your criteria
                  </TableCell>
                </TableRow>
              ) : (
                filteredTrucks.map((truck) => (
                  <TableRow
                    key={truck.id}
                    className={cn(
                      'border-border/50 cursor-pointer transition-colors',
                      !truck.isEnabled && 'opacity-50'
                    )}
                    onClick={() => handleTruckClick(truck)}
                  >
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium">{truck.plateNumber}</span>
                        <span className="text-xs text-muted-foreground">{truck.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm">{truck.driverName || '—'}</span>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={cn('capitalize', statusBadgeClasses[truck.status])}
                      >
                        {truck.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <span className="font-mono text-sm">{truck.speed} km/h</span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <div className="flex items-center gap-1 text-sm text-muted-foreground">
                        <MapPin className="h-3 w-3" />
                        <span>
                          {truck.latitude.toFixed(4)}, {truck.longitude.toFixed(4)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1 text-sm text-muted-foreground">
                        <Clock className="h-3 w-3" />
                        <span>{formatDistanceToNow(truck.lastUpdate, { addSuffix: true })}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                          <Button variant="ghost" size="icon" className="h-8 w-8">
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="bg-popover">
                          <DropdownMenuItem onClick={(e) => { e.stopPropagation(); navigate(`/trucks/${truck.id}`); }}>
                            <MapPin className="mr-2 h-4 w-4" />
                            View details
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleViewOnMap(truck); }}>
                            <MapPin className="mr-2 h-4 w-4" />
                            View on map
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleEdit(truck); }}>
                            <Pencil className="mr-2 h-4 w-4" />
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={(e) => { e.stopPropagation(); toggleTruckEnabled(truck.id); }}>
                            <Power className="mr-2 h-4 w-4" />
                            {truck.isEnabled ? 'Disable' : 'Enable'}
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={(e) => { e.stopPropagation(); handleDelete(truck); }}
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </Card>

      {/* Add/Edit Modal */}
      <TruckFormModal
        open={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setEditingTruck(null);
        }}
        truck={editingTruck}
      />
    </div>
  );
}
