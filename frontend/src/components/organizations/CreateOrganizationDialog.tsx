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
import type { OrganizationCreate } from '@/lib/api';

import { MIN_PASSWORD_LENGTH } from './shared';

const emptyForm = {
  name: '',
  admin_email: '',
  admin_password: '',
  contact_name: '',
  contact_phone: '',
  notes: '',
};

interface CreateOrganizationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (body: OrganizationCreate) => void;
  isPending: boolean;
  /**
   * Set by the parent once the company exists. Switches the dialog to its
   * hand-over state — the operator has to pass this login to the customer, so
   * it stays on screen until they dismiss it rather than vanishing with a toast.
   */
  createdAdminEmail: string | null;
  onDismissSuccess: () => void;
}

export function CreateOrganizationDialog({
  open,
  onOpenChange,
  onSubmit,
  isPending,
  createdAdminEmail,
  onDismissSuccess,
}: CreateOrganizationDialogProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState(emptyForm);

  // Never carry one customer's half-typed details into the next onboarding.
  useEffect(() => {
    if (open) setForm(emptyForm);
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('organizations.add')}</DialogTitle>
        </DialogHeader>
        {createdAdminEmail ? (
          <div className="space-y-4">
            <p className="text-sm font-medium">{t('organizations.created')}</p>
            <div className="rounded-md border border-border bg-muted/40 p-3">
              <p className="text-xs text-muted-foreground">{t('organizations.adminEmail')}</p>
              <p className="font-mono text-sm">{createdAdminEmail}</p>
            </div>
            <DialogFooter>
              <Button
                onClick={() => {
                  onDismissSuccess();
                  onOpenChange(false);
                }}
              >
                {t('common.cancel')}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              onSubmit({
                name: form.name.trim(),
                admin_email: form.admin_email.trim(),
                admin_password: form.admin_password,
                contact_name: form.contact_name.trim() || null,
                contact_phone: form.contact_phone.trim() || null,
                notes: form.notes.trim() || null,
              });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="org-name">{t('organizations.name')}</Label>
              <Input
                id="org-name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="org-contact">{t('organizations.contactName')}</Label>
                <Input
                  id="org-contact"
                  value={form.contact_name}
                  onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="org-phone">{t('organizations.contactPhone')}</Label>
                <Input
                  id="org-phone"
                  value={form.contact_phone}
                  onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="org-notes">{t('organizations.notes')}</Label>
              <Textarea
                id="org-notes"
                rows={2}
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">{t('organizations.notesHint')}</p>
            </div>

            <div className="space-y-3 rounded-md border border-border p-3">
              <div>
                <p className="text-sm font-medium">{t('organizations.adminSection')}</p>
                <p className="text-xs text-muted-foreground">
                  {t('organizations.adminSectionHint')}
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="org-admin-email">{t('organizations.adminEmail')}</Label>
                <Input
                  id="org-admin-email"
                  type="email"
                  required
                  value={form.admin_email}
                  onChange={(e) => setForm({ ...form, admin_email: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="org-admin-password">{t('organizations.adminPassword')}</Label>
                <Input
                  id="org-admin-password"
                  type="password"
                  required
                  minLength={MIN_PASSWORD_LENGTH}
                  value={form.admin_password}
                  onChange={(e) => setForm({ ...form, admin_password: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">{t('organizations.passwordHint')}</p>
              </div>
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
        )}
      </DialogContent>
    </Dialog>
  );
}
