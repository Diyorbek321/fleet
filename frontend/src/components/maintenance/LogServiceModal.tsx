import React, { useState, useEffect } from 'react';
import { useMaintenance } from '@/contexts/MaintenanceContext';
import { useTrucks } from '@/contexts/TruckContext';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ServiceType } from '@/types';
import { toast } from 'sonner';
import { format } from 'date-fns';

const serviceTypeLabels: Record<ServiceType, string> = {
  oil_change: 'Oil Change',
  tire_rotation: 'Tire Rotation',
  brake_inspection: 'Brake Inspection',
  engine_service: 'Engine Service',
  transmission: 'Transmission',
  other: 'Other',
};

interface LogServiceModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  intervalId?: string | null;
}

export function LogServiceModal({ open, onOpenChange, intervalId }: LogServiceModalProps) {
  const { serviceIntervals, addMaintenanceRecord } = useMaintenance();
  const { trucks } = useTrucks();
  
  const [formData, setFormData] = useState({
    truckId: '',
    serviceType: '' as ServiceType | '',
    date: format(new Date(), 'yyyy-MM-dd'),
    mileage: '',
    cost: '',
    vendor: '',
    notes: '',
  });
  
  // Pre-fill from interval if provided
  useEffect(() => {
    if (intervalId && open) {
      const interval = serviceIntervals.find(i => i.id === intervalId);
      if (interval) {
        setFormData(prev => ({
          ...prev,
          truckId: interval.truckId,
          serviceType: interval.serviceType,
        }));
      }
    }
  }, [intervalId, open, serviceIntervals]);
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!formData.truckId || !formData.serviceType || !formData.mileage || !formData.cost) {
      toast.error('Please fill in all required fields');
      return;
    }
    
    addMaintenanceRecord({
      truckId: formData.truckId,
      serviceType: formData.serviceType as ServiceType,
      date: new Date(formData.date),
      mileage: parseInt(formData.mileage),
      cost: parseFloat(formData.cost),
      vendor: formData.vendor || undefined,
      notes: formData.notes || undefined,
    });
    
    toast.success('Service logged successfully');
    onOpenChange(false);
    
    // Reset form
    setFormData({
      truckId: '',
      serviceType: '',
      date: format(new Date(), 'yyyy-MM-dd'),
      mileage: '',
      cost: '',
      vendor: '',
      notes: '',
    });
  };
  
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Log Service</DialogTitle>
          <DialogDescription>
            Record a completed maintenance service
          </DialogDescription>
        </DialogHeader>
        
        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="truck">Truck *</Label>
              <Select
                value={formData.truckId}
                onValueChange={(value) => setFormData(prev => ({ ...prev, truckId: value }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select truck" />
                </SelectTrigger>
                <SelectContent>
                  {trucks.filter(t => t.isEnabled).map(truck => (
                    <SelectItem key={truck.id} value={truck.id}>
                      {truck.name} ({truck.plateNumber})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="serviceType">Service Type *</Label>
              <Select
                value={formData.serviceType}
                onValueChange={(value) => setFormData(prev => ({ ...prev, serviceType: value as ServiceType }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select service" />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(serviceTypeLabels).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="date">Date *</Label>
              <Input
                id="date"
                type="date"
                value={formData.date}
                onChange={(e) => setFormData(prev => ({ ...prev, date: e.target.value }))}
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="mileage">Mileage *</Label>
              <Input
                id="mileage"
                type="number"
                placeholder="e.g., 50000"
                value={formData.mileage}
                onChange={(e) => setFormData(prev => ({ ...prev, mileage: e.target.value }))}
              />
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="cost">Cost ($) *</Label>
              <Input
                id="cost"
                type="number"
                step="0.01"
                placeholder="e.g., 85.00"
                value={formData.cost}
                onChange={(e) => setFormData(prev => ({ ...prev, cost: e.target.value }))}
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="vendor">Vendor</Label>
              <Input
                id="vendor"
                placeholder="Service provider name"
                value={formData.vendor}
                onChange={(e) => setFormData(prev => ({ ...prev, vendor: e.target.value }))}
              />
            </div>
          </div>
          
          <div className="space-y-2">
            <Label htmlFor="notes">Notes</Label>
            <Textarea
              id="notes"
              placeholder="Additional details about the service..."
              value={formData.notes}
              onChange={(e) => setFormData(prev => ({ ...prev, notes: e.target.value }))}
            />
          </div>
          
          <div className="flex justify-end gap-3 pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit">Log Service</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
