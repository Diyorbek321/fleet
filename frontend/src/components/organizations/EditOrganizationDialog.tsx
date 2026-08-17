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
import { Textarea } from '@/components/ui/textarea';
import type { Organization, OrganizationUpdate } from '@/lib/api';

interface EditOrganizationDialogProps {
  /** The company being edited; `null` closes the dialog. */
  target: Organization | null;
  onClose: () => void;
  onSubmit: (id: string, body: OrganizationUpdate) => void;
  isPending: boolean;
}

export function EditOrganizationDialog({
  target,
  onClose,
  onSubmit,
  isPending,
}: EditOrganizationDialogProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState({ name: '', contact_name: '', contact_phone: '', notes: '' });

  // Seed from whichever company was just opened, so the dialog never shows the
  // previously edited customer's details.
  useEffect(() => {
    if (!target) return;
    setForm({
      name: target.name,
      contact_name: target.contact_name ?? '',
      contact_phone: target.contact_phone ?? '',
      notes: target.notes ?? '',
    });
  }, [target]);

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{target?.name}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!target) return;
            onSubmit(target.id, {
              name: form.name.trim(),
              contact_name: form.contact_name.trim() || null,
              contact_phone: form.contact_phone.trim() || null,
              notes: form.notes.trim() || null,
            });
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="edit-name">{t('organizations.name')}</Label>
            <Input
              id="edit-name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="edit-contact">{t('organizations.contactName')}</Label>
              <Input
                id="edit-contact"
                value={form.contact_name}
                onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-phone">{t('organizations.contactPhone')}</Label>
              <Input
                id="edit-phone"
                value={form.contact_phone}
                onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-notes">{t('organizations.notes')}</Label>
            <Textarea
              id="edit-notes"
              rows={3}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">{t('organizations.notesHint')}</p>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
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
