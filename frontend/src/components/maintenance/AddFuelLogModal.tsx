import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMaintenance } from '@/contexts/MaintenanceContext';
import { useTrucks } from '@/contexts/TruckContext';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import { format } from '@/lib/datetime';

interface AddFuelLogModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddFuelLogModal({ open, onOpenChange }: AddFuelLogModalProps) {
  const { t } = useTranslation();
  const { addFuelLog } = useMaintenance();
  const { trucks } = useTrucks();
  
  const [formData, setFormData] = useState({
    truckId: '',
    date: format(new Date(), 'yyyy-MM-dd'),
    gallons: '',
    pricePerGallon: '',
    mileage: '',
    location: '',
  });
  
  const totalCost = formData.gallons && formData.pricePerGallon 
    ? (parseFloat(formData.gallons) * parseFloat(formData.pricePerGallon)).toFixed(2)
    : '0.00';
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!formData.truckId || !formData.gallons || !formData.pricePerGallon || !formData.mileage) {
      toast.error(t('maintenance.fuelModal.required'));
      return;
    }
    
    const gallons = parseFloat(formData.gallons);
    const pricePerGallon = parseFloat(formData.pricePerGallon);
    
    addFuelLog({
      truckId: formData.truckId,
      date: new Date(formData.date),
      gallons,
      pricePerGallon,
      totalCost: gallons * pricePerGallon,
      mileage: parseInt(formData.mileage),
      location: formData.location || undefined,
    });
    
    toast.success(t('maintenance.fuelModal.success'));
    onOpenChange(false);
    
    // Reset form
    setFormData({
      truckId: '',
      date: format(new Date(), 'yyyy-MM-dd'),
      gallons: '',
      pricePerGallon: '',
      mileage: '',
      location: '',
    });
  };
  
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[450px]">
        <DialogHeader>
          <DialogTitle>{t('maintenance.fuelModal.title')}</DialogTitle>
          <DialogDescription>
            {t('maintenance.fuelModal.description')}
          </DialogDescription>
        </DialogHeader>
        
        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          <div className="space-y-2">
            <Label htmlFor="truck">{t('maintenance.fuelModal.truck')}</Label>
            <Select
              value={formData.truckId}
              onValueChange={(value) => setFormData(prev => ({ ...prev, truckId: value }))}
            >
              <SelectTrigger>
                <SelectValue placeholder={t('maintenance.fuelModal.selectTruck')} />
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
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="date">{t('maintenance.fuelModal.date')}</Label>
              <Input
                id="date"
                type="date"
                value={formData.date}
                onChange={(e) => setFormData(prev => ({ ...prev, date: e.target.value }))}
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="mileage">{t('maintenance.fuelModal.odometer')}</Label>
              <Input
                id="mileage"
                type="number"
                placeholder={t('maintenance.fuelModal.odometerPlaceholder')}
                value={formData.mileage}
                onChange={(e) => setFormData(prev => ({ ...prev, mileage: e.target.value }))}
              />
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="gallons">{t('maintenance.fuelModal.litres')}</Label>
              <Input
                id="gallons"
                type="number"
                step="0.1"
                placeholder={t('maintenance.fuelModal.litresPlaceholder')}
                value={formData.gallons}
                onChange={(e) => setFormData(prev => ({ ...prev, gallons: e.target.value }))}
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="pricePerGallon">{t('maintenance.fuelModal.pricePerLitre')}</Label>
              <Input
                id="pricePerGallon"
                type="number"
                step="0.01"
                placeholder={t('maintenance.fuelModal.pricePlaceholder')}
                value={formData.pricePerGallon}
                onChange={(e) => setFormData(prev => ({ ...prev, pricePerGallon: e.target.value }))}
              />
            </div>
          </div>
          
          <div className="space-y-2">
            <Label htmlFor="location">{t('maintenance.fuelModal.location')}</Label>
            <Input
              id="location"
              placeholder={t('maintenance.fuelModal.locationPlaceholder')}
              value={formData.location}
              onChange={(e) => setFormData(prev => ({ ...prev, location: e.target.value }))}
            />
          </div>
          
          {/* Calculated Total */}
          <div className="p-3 rounded-lg bg-muted/50 border border-border">
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">{t('maintenance.fuelModal.calculatedTotal')}</span>
              <span className="text-xl font-bold text-foreground">{totalCost} {t('common.currency')}</span>
            </div>
          </div>
          
          <div className="flex justify-end gap-3 pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit">{t('maintenance.fuelModal.submit')}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
