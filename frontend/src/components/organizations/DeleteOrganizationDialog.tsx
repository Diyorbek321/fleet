import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { Organization } from '@/lib/api';

interface DeleteOrganizationDialogProps {
  /** The company being deleted; `null` closes the dialog. */
  target: Organization | null;
  onClose: () => void;
  onConfirm: (org: Organization, confirm: string) => void;
  isPending: boolean;
}

/**
 * Typed-name confirmation, mirroring the backend's `?confirm=` guard.
 *
 * Deleting a company cascades to its trucks, drivers and trips, so the operator
 * must retype the exact name — a stray click cannot destroy a customer.
 */
export function DeleteOrganizationDialog({
  target,
  onClose,
  onConfirm,
  isPending,
}: DeleteOrganizationDialogProps) {
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState('');

  // Reset per company: a name left in the box from a previous attempt must
  // never pre-arm the delete button for a different customer.
  useEffect(() => {
    setConfirm('');
  }, [target]);

  const matches = target !== null && confirm === target.name;

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t('organizations.deleteTitle')}: {target?.name}
          </DialogTitle>
          <DialogDescription>{t('organizations.deleteWarning')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="delete-confirm">{t('organizations.deleteConfirmLabel')}</Label>
          <Input
            id="delete-confirm"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          {confirm.length > 0 && !matches && (
            <p className="text-xs text-destructive">{t('organizations.deleteConfirmMismatch')}</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="destructive"
            disabled={isPending || !matches}
            onClick={() => target && onConfirm(target, confirm)}
          >
            {t('common.delete')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
