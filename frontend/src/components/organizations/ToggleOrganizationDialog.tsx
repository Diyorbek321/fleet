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
import type { Organization } from '@/lib/api';

interface ToggleOrganizationDialogProps {
  /** The company being suspended or reactivated; `null` closes the dialog. */
  target: Organization | null;
  onClose: () => void;
  onConfirm: (org: Organization) => void;
  isPending: boolean;
}

/** Suspending cuts off a paying customer's whole company, so it is confirmed. */
export function ToggleOrganizationDialog({
  target,
  onClose,
  onConfirm,
  isPending,
}: ToggleOrganizationDialogProps) {
  const { t } = useTranslation();
  const actionLabel = target?.is_active
    ? t('organizations.suspend')
    : t('organizations.activate');

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {actionLabel}: {target?.name}
          </DialogTitle>
          <DialogDescription>{t('organizations.suspendHint')}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant={target?.is_active ? 'destructive' : 'default'}
            disabled={isPending}
            onClick={() => target && onConfirm(target)}
          >
            {actionLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
