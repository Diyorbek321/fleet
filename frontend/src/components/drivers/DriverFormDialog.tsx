import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { Driver, DriverInput } from '@/lib/drivers';

interface FormState {
  name: string;
  passportNumber: string;
  phone: string;
  phone2: string;
  phone3: string;
  adr: boolean;
}

function stateFor(driver: Driver | null): FormState {
  return {
    name: driver?.name ?? '',
    passportNumber: driver?.passportNumber ?? '',
    phone: driver?.phone ?? '',
    phone2: driver?.phone2 ?? '',
    phone3: driver?.phone3 ?? '',
    adr: driver?.adr ?? false,
  };
}

/** One number per country on the route; the field order is the order a
 *  driver crosses them. */
const PHONE_FIELDS = [
  { key: 'phone', label: 'drivers.phoneUz', placeholder: '+998 90 123 45 67' },
  { key: 'phone2', label: 'drivers.phoneKz', placeholder: '+7 771 123 45 67' },
  { key: 'phone3', label: 'drivers.phoneRu', placeholder: '+7 903 123 45 67' },
] as const;

interface DriverFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The driver being edited, or null to add a new one. */
  driver: Driver | null;
  isPending: boolean;
  onSubmit: (input: DriverInput) => void;
}

export function DriverFormDialog({
  open,
  onOpenChange,
  driver,
  isPending,
  onSubmit,
}: DriverFormDialogProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState<FormState>(() => stateFor(driver));

  // Re-seed whenever the dialog opens, so an edit starts from the record and
  // an add starts blank — whichever was open last.
  useEffect(() => {
    if (open) setForm(stateFor(driver));
  }, [open, driver]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{driver ? t('drivers.edit') : t('drivers.add')}</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit({
              name: form.name.trim(),
              passportNumber: form.passportNumber.trim().toUpperCase(),
              phone: form.phone.trim(),
              phone2: form.phone2.trim(),
              phone3: form.phone3.trim(),
              adr: form.adr,
            });
          }}
          className="space-y-3"
        >
          <div className="space-y-2">
            <Label htmlFor="d-name">{t('drivers.name')}</Label>
            <Input
              id="d-name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="d-passport">{t('drivers.passport')}</Label>
            <Input
              id="d-passport"
              maxLength={20}
              placeholder="AB1234567"
              value={form.passportNumber}
              onChange={(e) => setForm({ ...form, passportNumber: e.target.value })}
            />
          </div>
          {PHONE_FIELDS.map(({ key, label, placeholder }) => (
            <div key={key} className="space-y-2">
              <Label htmlFor={`d-${key}`}>{t(label)}</Label>
              <Input
                id={`d-${key}`}
                inputMode="tel"
                maxLength={20}
                placeholder={placeholder}
                value={form[key]}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              />
            </div>
          ))}
          <div className="space-y-2">
            <Label>{t('drivers.adr')}</Label>
            <Select
              value={form.adr ? 'yes' : 'no'}
              onValueChange={(v) => setForm({ ...form, adr: v === 'yes' })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="no">{t('common.no')}</SelectItem>
                <SelectItem value="yes">{t('common.yes')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
