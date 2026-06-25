import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useTrucks } from '@/contexts/TruckContext';
import { logger } from '@/lib/logger';
import { Truck } from '@/types';

const truckSchema = z.object({
  plateNumber: z.string().min(1, 'Plate number is required').max(20, 'Plate number is too long'),
  name: z.string().min(1, 'Truck name is required').max(50, 'Name is too long'),
  deviceImei: z.string().min(15, 'IMEI must be at least 15 digits').max(17, 'IMEI is too long'),
  model: z.string().max(50, 'Model name is too long').optional(),
  driverName: z.string().max(50, 'Driver name is too long').optional(),
});

type TruckFormData = z.infer<typeof truckSchema>;

interface TruckFormModalProps {
  open: boolean;
  onClose: () => void;
  truck: Truck | null;
}

export function TruckFormModal({ open, onClose, truck }: TruckFormModalProps) {
  const { addTruck, updateTruck } = useTrucks();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isEditing = !!truck;

  const form = useForm<TruckFormData>({
    resolver: zodResolver(truckSchema),
    defaultValues: {
      plateNumber: truck?.plateNumber || '',
      name: truck?.name || '',
      deviceImei: truck?.deviceImei || '',
      model: truck?.model || '',
      driverName: truck?.driverName || '',
    },
  });

  // Reset form when truck changes
  React.useEffect(() => {
    if (open) {
      form.reset({
        plateNumber: truck?.plateNumber || '',
        name: truck?.name || '',
        deviceImei: truck?.deviceImei || '',
        model: truck?.model || '',
        driverName: truck?.driverName || '',
      });
    }
  }, [truck, open, form]);

  const onSubmit = async (data: TruckFormData) => {
    setIsSubmitting(true);
    try {
      if (isEditing) {
        await updateTruck(truck.id, data);
      } else {
        await addTruck({
          plateNumber: data.plateNumber,
          name: data.name,
          deviceImei: data.deviceImei,
          model: data.model || '',
          driverName: data.driverName || '',
          isEnabled: true,
        });
      }
      onClose();
    } catch (error) {
      logger.error('Error saving truck:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md bg-card border-border">
        <DialogHeader>
          <DialogTitle>{isEditing ? 'Edit Truck' : 'Add New Truck'}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? 'Update the truck details below.'
              : 'Enter the details for your new truck.'}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="plateNumber"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Plate Number *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="ABC 1234"
                      className="bg-secondary/50 border-0"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Truck Name *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g., Freightliner Cascadia"
                      className="bg-secondary/50 border-0"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="deviceImei"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Device IMEI *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="GPS tracker IMEI number"
                      className="bg-secondary/50 border-0"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="model"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Model (Optional)</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g., Cascadia 2024"
                      className="bg-secondary/50 border-0"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="driverName"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Driver Name (Optional)</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Assigned driver"
                      className="bg-secondary/50 border-0"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : isEditing ? (
                  'Update Truck'
                ) : (
                  'Add Truck'
                )}
              </Button>
            </div>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
