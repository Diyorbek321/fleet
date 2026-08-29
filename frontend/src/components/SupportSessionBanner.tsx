import { useTranslation } from 'react-i18next';
import { Eye, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { supportSession } from '@/lib/api';

/**
 * Shown across the whole app while a platform operator is looking at one
 * customer's data.
 *
 * Deliberately loud and always present. Every screen behind it shows somebody
 * else's numbers, and an operator who forgets that will misread a figure — or
 * reach for an action the backend then refuses, and conclude the product is
 * broken. The one thing this must never be is subtle.
 */
export function SupportSessionBanner() {
  const { t } = useTranslation();
  const session = supportSession.get();

  if (!session) return null;

  return (
    <div className="flex items-center justify-between gap-3 bg-amber-500 px-4 py-2 text-sm font-medium text-amber-950">
      <div className="flex min-w-0 items-center gap-2">
        <Eye className="h-4 w-4 shrink-0" />
        <span className="truncate">
          {t('support.viewing')} <strong>{session.orgName}</strong> — {t('support.readOnly')}
        </span>
      </div>
      <Button
        size="sm"
        variant="outline"
        className="h-7 shrink-0 border-amber-950/30 bg-amber-400 text-amber-950 hover:bg-amber-300"
        onClick={endSupportSession}
      >
        <X className="mr-1 h-3 w-3" />
        {t('support.exit')}
      </Button>
    </div>
  );
}

/**
 * Enter or leave a support session with a full page load, not a route change.
 *
 * Entering changes the identity of every piece of data the app holds: the
 * cached truck list, the dashboard figures, the open dialog's contents. A
 * reload is the only way to guarantee that nothing fetched as one party is
 * still on screen while the header says the other — and getting that wrong
 * means showing one customer's numbers under another customer's name.
 */
export function startSupportSession(orgId: string, orgName: string): void {
  supportSession.set({ orgId, orgName });
  window.location.href = '/dashboard';
}

export function endSupportSession(): void {
  supportSession.clear();
  window.location.href = '/organizations';
}
