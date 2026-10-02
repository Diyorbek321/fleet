import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { useTrucks } from '@/contexts/TruckContext';
import { logger } from '@/lib/logger';
import { Truck, TrailerVolume } from '@/types';

type Translate = ReturnType<typeof useTranslation>['t'];

/** The two capacity classes the market quotes; mirrors the backend enum. */
const TRAILER_VOLUMES: TrailerVolume[] = ['standart', 'mega'];

// Radix's Select cannot hold an empty-string value, so a sentinel stands in
// for "this tractor has no trailer on it".
const NO_VOLUME = '__none__';

/** Matches the backend's limit: room for "tractor / trailer" plates. */
const PLATE_MAX = 40;

/** One date per country a rig is insured for, in the order they are crossed. */
const INSURANCE_FIELDS = [
  { name: 'insuranceExpiry', labelKey: 'insurance.country.uz' },
  { name: 'insuranceExpiryKz', labelKey: 'insurance.country.kz' },
  { name: 'insuranceExpiryRf', labelKey: 'insurance.country.rf' },
] as const;

const buildTruckSchema = (t: Translate) =>
  z.object({
    plateNumber: z
      .string()
      .min(1, t('trucks.form.plateRequired'))
      .max(PLATE_MAX, t('trucks.form.plateTooLong')),
    tractorBrand: z.string().max(60, t('trucks.form.brandTooLong')).optional(),
    trailerBrand: z.string().max(60, t('trucks.form.brandTooLong')).optional(),
    trailerVolume: z.enum(['standart', 'mega']).optional(),
    // ISO date from <input type="date">, or '' when left blank.
    insuranceExpiry: z.string().optional(),
    insuranceExpiryKz: z.string().optional(),
    insuranceExpiryRf: z.string().optional(),
  });

type TruckFormData = z.infer<ReturnType<typeof buildTruckSchema>>;

/** One definition of "what this form starts with", used by both the initial
 *  mount and the reset when a different truck is opened. Kept as a function
 *  because the two used to be copies and drifted the first time a field was
 *  added to one of them. */
function defaultsFor(truck: Truck | null): TruckFormData {
  return {
    plateNumber: truck?.plateNumber || '',
    tractorBrand: truck?.tractorBrand || '',
    trailerBrand: truck?.trailerBrand || '',
    trailerVolume: truck?.trailerVolume,
    insuranceExpiry: truck?.insuranceExpiry || '',
    insuranceExpiryKz: truck?.insuranceExpiryKz || '',
    insuranceExpiryRf: truck?.insuranceExpiryRf || '',
  };
}

interface TruckFormModalProps {
  open: boolean;
  onClose: () => void;
  truck: Truck | null;
}

export function TruckFormModal({ open, onClose, truck }: TruckFormModalProps) {
  const { t } = useTranslation();
  const { addTruck, updateTruck } = useTrucks();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const truckSchema = React.useMemo(() => buildTruckSchema(t), [t]);

  const isEditing = !!truck;

  const form = useForm<TruckFormData>({
    resolver: zodResolver(truckSchema),
    defaultValues: defaultsFor(truck),
  });

  // Reset form when truck changes
  React.useEffect(() => {
    if (open) {
      form.reset(defaultsFor(truck));
    }
  }, [truck, open, form]);

  const onSubmit = async (data: TruckFormData) => {
    setIsSubmitting(true);
    try {
      // No name: the truck is known by its plate, and the backend names a
      // new one after it. The driver is attached from the Drivers page.
      if (isEditing) {
        await updateTruck(truck.id, {
          ...data,
          insuranceExpiry: data.insuranceExpiry || null,
          insuranceExpiryKz: data.insuranceExpiryKz || null,
          insuranceExpiryRf: data.insuranceExpiryRf || null,
        });
      } else {
        await addTruck({
          plateNumber: data.plateNumber,
          tractorBrand: data.tractorBrand || undefined,
          trailerBrand: data.trailerBrand || undefined,
          trailerVolume: data.trailerVolume,
          insuranceExpiry: data.insuranceExpiry || null,
          insuranceExpiryKz: data.insuranceExpiryKz || null,
          insuranceExpiryRf: data.insuranceExpiryRf || null,
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
      <DialogContent className="sm:max-w-md bg-card border-border max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEditing ? t('trucks.form.editTitle') : t('trucks.form.addTitle')}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? t('trucks.form.editDescription')
              : t('trucks.form.addDescription')}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="plateNumber"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('trucks.form.plate')}</FormLabel>
                  <FormControl>
                    <Input
                      placeholder={t('trucks.form.platePlaceholder')}
                      maxLength={PLATE_MAX}
                      className="bg-secondary/50 border-0"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* A rig is two vehicles, so it takes two makes. Side by side
                because they are filled in together, off one registration. */}
            <div className="grid grid-cols-2 gap-3">
              <FormField
                control={form.control}
                name="tractorBrand"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('trucks.form.tractorBrand')}</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t('trucks.form.tractorBrandPlaceholder')}
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
                name="trailerBrand"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('trucks.form.trailerBrand')}</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t('trucks.form.trailerBrandPlaceholder')}
                        className="bg-secondary/50 border-0"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="trailerVolume"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('trucks.form.trailerVolume')}</FormLabel>
                  <Select
                    value={field.value ?? NO_VOLUME}
                    onValueChange={(v) =>
                      field.onChange(v === NO_VOLUME ? undefined : (v as TrailerVolume))
                    }
                  >
                    <FormControl>
                      <SelectTrigger className="bg-secondary/50 border-0">
                        <SelectValue placeholder={t('trucks.form.trailerVolumeNone')} />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value={NO_VOLUME}>
                        {t('trucks.form.trailerVolumeNone')}
                      </SelectItem>
                      {TRAILER_VOLUMES.map((v) => (
                        <SelectItem key={v} value={v}>
                          {t(`trucks.volume.${v}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t('trucks.form.insuranceExpiry')}</legend>
              <div className="grid grid-cols-3 gap-2">
                {INSURANCE_FIELDS.map(({ name, labelKey }) => (
                  <FormField
                    key={name}
                    control={form.control}
                    name={name}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs text-muted-foreground">{t(labelKey)}</FormLabel>
                        <FormControl>
                          <Input type="date" className="bg-secondary/50 border-0 px-2" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                ))}
              </div>
            </fieldset>

            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {t('common.saving')}
                  </>
                ) : isEditing ? (
                  t('trucks.form.update')
                ) : (
                  t('trucks.form.create')
                )}
              </Button>
            </div>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
