import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
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
import { format } from '@/lib/datetime';

/** Kept in display order; the label itself comes from `maintenance.serviceTypes`. */
const SERVICE_TYPES: ServiceType[] = [
  'oil_change',
  'tire_rotation',
  'brake_inspection',
  'engine_service',
  'transmission',
  'other',
];

interface LogServiceModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  intervalId?: string | null;
}

export function LogServiceModal({ open, onOpenChange, intervalId }: LogServiceModalProps) {
  const { t } = useTranslation();
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
      toast.error(t('maintenance.serviceModal.required'));
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
    
    toast.success(t('maintenance.serviceModal.success'));
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
          <DialogTitle>{t('maintenance.serviceModal.title')}</DialogTitle>
          <DialogDescription>
            {t('maintenance.serviceModal.description')}
          </DialogDescription>
        </DialogHeader>
        
        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="truck">{t('maintenance.serviceModal.truck')}</Label>
              <Select
                value={formData.truckId}
                onValueChange={(value) => setFormData(prev => ({ ...prev, truckId: value }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('maintenance.serviceModal.selectTruck')} />
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
              <Label htmlFor="serviceType">{t('maintenance.serviceModal.serviceType')}</Label>
              <Select
                value={formData.serviceType}
                onValueChange={(value) => setFormData(prev => ({ ...prev, serviceType: value as ServiceType }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('maintenance.serviceModal.selectService')} />
                </SelectTrigger>
                <SelectContent>
                  {SERVICE_TYPES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`maintenance.serviceTypes.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="date">{t('maintenance.serviceModal.date')}</Label>
              <Input
                id="date"
                type="date"
                value={formData.date}
                onChange={(e) => setFormData(prev => ({ ...prev, date: e.target.value }))}
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="mileage">{t('maintenance.serviceModal.mileage')}</Label>
              <Input
                id="mileage"
                type="number"
                placeholder={t('maintenance.serviceModal.mileagePlaceholder')}
                value={formData.mileage}
                onChange={(e) => setFormData(prev => ({ ...prev, mileage: e.target.value }))}
              />
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="cost">{t('maintenance.serviceModal.cost')}</Label>
              <Input
                id="cost"
                type="number"
                step="0.01"
                placeholder={t('maintenance.serviceModal.costPlaceholder')}
                value={formData.cost}
                onChange={(e) => setFormData(prev => ({ ...prev, cost: e.target.value }))}
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="vendor">{t('maintenance.serviceModal.vendor')}</Label>
              <Input
                id="vendor"
                placeholder={t('maintenance.serviceModal.vendorPlaceholder')}
                value={formData.vendor}
                onChange={(e) => setFormData(prev => ({ ...prev, vendor: e.target.value }))}
              />
            </div>
          </div>
          
          <div className="space-y-2">
            <Label htmlFor="notes">{t('maintenance.serviceModal.notes')}</Label>
            <Textarea
              id="notes"
              placeholder={t('maintenance.serviceModal.notesPlaceholder')}
              value={formData.notes}
              onChange={(e) => setFormData(prev => ({ ...prev, notes: e.target.value }))}
            />
          </div>
          
          <div className="flex justify-end gap-3 pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit">{t('maintenance.serviceModal.title')}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
