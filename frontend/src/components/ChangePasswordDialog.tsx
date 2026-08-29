import { useState } from 'react';
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
import { useAuth } from '@/contexts/AuthContext';
import { ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Blocks until the password is changed: no cancel button, no dismissal.
   *
   * Used when the account is on a password an admin chose. Letting it be
   * dismissed would leave the flag set forever and the prompt reappearing on
   * every page — worse for the user than simply requiring the change, and it
   * would not protect the account either way.
   */
  forced?: boolean;
}

export function ChangePasswordDialog({ open, onOpenChange, forced = false }: Props) {
  const { t } = useTranslation();
  const { changePassword } = useAuth();

  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setCurrent('');
    setNext('');
    setConfirm('');
    setError(null);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    // Checked here rather than server-side: the confirmation field exists to
    // catch a typo before it locks the user out, and the server has no business
    // knowing the password was typed twice.
    if (next !== confirm) {
      setError(t('auth.passwordsDoNotMatch'));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await changePassword(current, next);
      toast({ title: t('auth.passwordChanged'), description: t('auth.otherDevicesSignedOut') });
      reset();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t('common.errorOccurred'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (forced) return;
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent
        // A forced dialog must not close on Escape or an outside click either;
        // hiding the close button alone would leave both escape hatches open.
        onEscapeKeyDown={(e) => forced && e.preventDefault()}
        onPointerDownOutside={(e) => forced && e.preventDefault()}
        onInteractOutside={(e) => forced && e.preventDefault()}
        hideClose={forced}
      >
        <DialogHeader>
          <DialogTitle>{t('auth.changePassword')}</DialogTitle>
          <DialogDescription>
            {forced ? t('auth.mustChangePassword') : t('auth.changePasswordHint')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="cp-current">{t('auth.currentPassword')}</Label>
            <Input
              id="cp-current"
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cp-new">{t('auth.newPassword')}</Label>
            <Input
              id="cp-new"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t('users.passwordHint')}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="cp-confirm">{t('auth.confirmPassword')}</Label>
            <Input
              id="cp-confirm"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <DialogFooter>
            {!forced && (
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t('common.cancel')}
              </Button>
            )}
            <Button type="submit" disabled={saving}>
              {saving ? t('common.saving') : t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
