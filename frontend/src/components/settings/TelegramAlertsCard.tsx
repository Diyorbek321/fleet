import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Copy, ExternalLink, Loader2, Send, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { ApiError } from '@/lib/api';
import {
  ALERT_KINDS,
  ALERT_SEVERITIES,
  DEFAULT_QUIET_FROM,
  DEFAULT_QUIET_TO,
  HOURS,
  formatHour,
  ownerAlertsApi,
  type AlertKind,
  type AlertSeverity,
  type TelegramAccount,
  type TelegramAccountUpdate,
} from '@/lib/ownerAlerts';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from '@/hooks/use-toast';

const QUERY_KEY = ['org', 'telegram'] as const;

/**
 * Where the company's owner alerts go, and how loud they are.
 *
 * The panel never sees a chat id. An admin mints a link here, opens it on the
 * phone that should receive the alerts, and Telegram itself tells the webhook
 * which chat to bind — so this card shows a link and a status, never an
 * address it could have chosen.
 *
 * The preferences below matter more than they look. Alert fatigue is this
 * feature's main failure mode: an owner who mutes the bot in week two never
 * comes back, and the only defence is that turning down one kind of noise is
 * easier than silencing everything. So every knob saves on the spot — a
 * "Save" button between an owner and a quieter night is a button they will not
 * find in time.
 */
export function TelegramAlertsCard() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'superadmin';

  const [label, setLabel] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [pendingUnlinkId, setPendingUnlinkId] = useState<string | null>(null);

  const accountsQuery = useQuery({
    queryKey: QUERY_KEY,
    queryFn: ownerAlertsApi.list,
    // Activation happens in Telegram, on another device, with nothing to tell
    // this tab about it. Poll only while something is actually waiting to be
    // opened — once every chat is bound there is nothing left to discover.
    refetchInterval: (query) =>
      query.state.data?.some((account) => !account.activated) ? 15_000 : false,
  });

  const linkMutation = useMutation({
    mutationFn: () => ownerAlertsApi.link({ label: label.trim() || null }),
    onSuccess: () => {
      setLabel('');
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast({
        title: t('telegramAlerts.linkCreated'),
        description: t('telegramAlerts.linkCreatedHint'),
      });
    },
    onError: (error: unknown) =>
      toast({
        title: t('telegramAlerts.linkFailed'),
        description: error instanceof ApiError ? error.detail : undefined,
        variant: 'destructive',
      }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: TelegramAccountUpdate }) =>
      ownerAlertsApi.update(id, body),
    onSuccess: (saved) => {
      // Replace the one row rather than refetching: the list is polled, and a
      // refetch here would redraw every other chat's controls mid-click.
      queryClient.setQueryData<TelegramAccount[]>(QUERY_KEY, (prev) =>
        prev?.map((account) => (account.id === saved.id ? saved : account)),
      );
    },
    onError: (error: unknown) =>
      toast({
        title: t('telegramAlerts.saveFailed'),
        description: error instanceof ApiError ? error.detail : undefined,
        variant: 'destructive',
      }),
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => ownerAlertsApi.test(id),
    onSuccess: (result) =>
      toast(
        result.sent
          ? { title: t('telegramAlerts.testSent') }
          : // Telegram accepted the request and refused the message — the chat
            // is bound but unreachable, which is a different problem from a
            // failed call and must not be reported as success.
            { title: t('telegramAlerts.testRejected'), variant: 'destructive' },
      ),
    onError: (error: unknown) =>
      toast({
        title: t('telegramAlerts.testFailed'),
        description: error instanceof ApiError ? error.detail : undefined,
        variant: 'destructive',
      }),
  });

  const unlinkMutation = useMutation({
    mutationFn: (id: string) => ownerAlertsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast({ title: t('telegramAlerts.unlinked') });
    },
    onError: (error: unknown) =>
      toast({
        title: t('telegramAlerts.unlinkFailed'),
        description: error instanceof ApiError ? error.detail : undefined,
        variant: 'destructive',
      }),
  });

  function copyLink(account: TelegramAccount): void {
    if (!account.deep_link) return;
    navigator.clipboard.writeText(account.deep_link).then(
      () => {
        setCopiedId(account.id);
        window.setTimeout(
          () => setCopiedId((prev) => (prev === account.id ? null : prev)),
          1500,
        );
        toast({ title: t('telegramAlerts.copied') });
      },
      () => toast({ title: t('telegramAlerts.copyFailed'), variant: 'destructive' }),
    );
  }

  const accounts = accountsQuery.data ?? [];

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Send className="h-5 w-5" /> {t('telegramAlerts.title')}
        </CardTitle>
        <CardDescription>{t('telegramAlerts.description')}</CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {canEdit && (
          <form
            className="grid gap-3 rounded-lg border border-dashed border-border/60 p-3 sm:grid-cols-[1fr_auto]"
            onSubmit={(e) => {
              e.preventDefault();
              if (!linkMutation.isPending) linkMutation.mutate();
            }}
          >
            <div className="space-y-1">
              <Label htmlFor="telegram-label" className="text-xs">
                {t('telegramAlerts.labelLabel')}
              </Label>
              <Input
                id="telegram-label"
                value={label}
                maxLength={120}
                placeholder={t('telegramAlerts.labelPlaceholder')}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={linkMutation.isPending} className="w-full sm:w-auto">
                {linkMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t('telegramAlerts.connectButton')}
              </Button>
            </div>
          </form>
        )}

        {accountsQuery.isLoading ? (
          <Skeleton className="h-28 w-full" />
        ) : accountsQuery.isError ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t('telegramAlerts.loadFailed')}
          </p>
        ) : accounts.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t('telegramAlerts.empty')}
          </p>
        ) : (
          <ul className="space-y-3">
            {accounts.map((account) => (
              <li
                key={account.id}
                className="space-y-3 rounded-lg border border-border/50 bg-muted/40 p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">
                      {account.label || t('telegramAlerts.unnamed')}
                    </span>
                    {!account.activated ? (
                      <Badge variant="outline">{t('telegramAlerts.statusPending')}</Badge>
                    ) : account.is_active ? (
                      <Badge className="gap-1">
                        <Check className="h-3 w-3" /> {t('telegramAlerts.statusActive')}
                      </Badge>
                    ) : (
                      <Badge variant="secondary">{t('telegramAlerts.statusPaused')}</Badge>
                    )}
                  </div>

                  {canEdit && (
                    <div className="flex items-center gap-1">
                      {account.activated && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={testMutation.isPending}
                          onClick={() => testMutation.mutate(account.id)}
                        >
                          {t('telegramAlerts.testButton')}
                        </Button>
                      )}
                      <Button
                        variant="destructive"
                        size="sm"
                        aria-label={t('telegramAlerts.unlink')}
                        onClick={() => setPendingUnlinkId(account.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </div>

                {account.deep_link ? (
                  <PendingLink
                    link={account.deep_link}
                    copied={copiedId === account.id}
                    onCopy={() => copyLink(account)}
                  />
                ) : (
                  <AccountPreferences
                    account={account}
                    canEdit={canEdit}
                    onChange={(body) => updateMutation.mutate({ id: account.id, body })}
                  />
                )}
              </li>
            ))}
          </ul>
        )}

        {!canEdit && <p className="text-xs text-muted-foreground">{t('telegramAlerts.readOnly')}</p>}
      </CardContent>

      <AlertDialog
        open={pendingUnlinkId !== null}
        onOpenChange={(open) => !open && setPendingUnlinkId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('telegramAlerts.confirmUnlinkTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('telegramAlerts.confirmUnlinkDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingUnlinkId) unlinkMutation.mutate(pendingUnlinkId);
                setPendingUnlinkId(null);
              }}
            >
              {t('telegramAlerts.unlink')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}

/**
 * The link, twice.
 *
 * An owner reading this on a desktop opens Telegram on their phone, so the
 * anchor is useless to them and the raw string is the only thing that travels.
 * An owner reading it on the phone itself wants one tap. Neither audience can
 * be dropped, so both get their affordance.
 */
function PendingLink({
  link,
  copied,
  onCopy,
}: {
  link: string;
  copied: boolean;
  onCopy: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">{t('telegramAlerts.deepLinkHint')}</p>
      <div className="flex flex-wrap items-center gap-2">
        <a
          href={link}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-sm font-medium text-primary underline underline-offset-4"
        >
          <ExternalLink className="h-3.5 w-3.5" /> {t('telegramAlerts.openLink')}
        </a>
        <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1 text-xs">
          {link}
        </code>
        <Button variant="outline" size="sm" aria-label={t('telegramAlerts.copy')} onClick={onCopy}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  );
}

/** One activated chat's delivery preferences: what, how loud, and when not. */
function AccountPreferences({
  account,
  canEdit,
  onChange,
}: {
  account: TelegramAccount;
  canEdit: boolean;
  onChange: (body: TelegramAccountUpdate) => void;
}) {
  const { t } = useTranslation();
  const quietOn = account.quiet_from_hour !== null && account.quiet_to_hour !== null;

  function toggleKind(kind: AlertKind, wanted: boolean): void {
    // Derived from the server's own array, so a kind this build does not know
    // about survives the round trip instead of being quietly un-muted.
    const muted = wanted
      ? account.muted_kinds.filter((k) => k !== kind)
      : [...account.muted_kinds, kind];
    onChange({ muted_kinds: muted });
  }

  return (
    <div className="space-y-4 border-t border-border/50 pt-3">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={`delivery-${account.id}`}>{t('telegramAlerts.deliveryLabel')}</Label>
        <Switch
          id={`delivery-${account.id}`}
          aria-label={t('telegramAlerts.deliveryLabel')}
          checked={account.is_active}
          disabled={!canEdit}
          onCheckedChange={(checked) => onChange({ is_active: checked })}
        />
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium">{t('telegramAlerts.kindsTitle')}</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {ALERT_KINDS.map((kind) => {
            const id = `kind-${account.id}-${kind}`;
            const name = t(`telegramAlerts.kinds.${kind}`);
            return (
              <div key={kind} className="flex items-center justify-between gap-2">
                <Label htmlFor={id} className="text-sm font-normal">
                  {name}
                </Label>
                <Switch
                  id={id}
                  aria-label={name}
                  checked={!account.muted_kinds.includes(kind)}
                  disabled={!canEdit}
                  onCheckedChange={(checked) => toggleKind(kind, checked)}
                />
              </div>
            );
          })}
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`severity-${account.id}`}>{t('telegramAlerts.severityLabel')}</Label>
        <Select
          value={account.min_severity}
          disabled={!canEdit}
          onValueChange={(value) => onChange({ min_severity: value as AlertSeverity })}
        >
          <SelectTrigger id={`severity-${account.id}`} className="w-full sm:w-72">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ALERT_SEVERITIES.map((severity) => (
              <SelectItem key={severity} value={severity}>
                {t(`telegramAlerts.severity.${severity}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">{t('telegramAlerts.severityHint')}</p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor={`quiet-${account.id}`}>{t('telegramAlerts.quietLabel')}</Label>
          <Switch
            id={`quiet-${account.id}`}
            aria-label={t('telegramAlerts.quietLabel')}
            checked={quietOn}
            disabled={!canEdit}
            onCheckedChange={(checked) =>
              onChange(
                checked
                  ? { quiet_from_hour: DEFAULT_QUIET_FROM, quiet_to_hour: DEFAULT_QUIET_TO }
                  : // Both null, not one: a half-open window is a state the
                    // backend has no reading for.
                    { quiet_from_hour: null, quiet_to_hour: null },
              )
            }
          />
        </div>
        {quietOn && (
          <div className="flex flex-wrap items-end gap-2">
            <HourSelect
              id={`quiet-from-${account.id}`}
              labelKey="telegramAlerts.quietFrom"
              value={account.quiet_from_hour as number}
              disabled={!canEdit}
              onChange={(hour) => onChange({ quiet_from_hour: hour })}
            />
            <HourSelect
              id={`quiet-to-${account.id}`}
              labelKey="telegramAlerts.quietTo"
              value={account.quiet_to_hour as number}
              disabled={!canEdit}
              onChange={(hour) => onChange({ quiet_to_hour: hour })}
            />
          </div>
        )}
        <p className="text-xs text-muted-foreground">{t('telegramAlerts.quietHint')}</p>
      </div>
    </div>
  );
}

/**
 * A whole-hour picker. A list of 24 fixed choices rather than a number field:
 * there is no such thing as a typo here, and no draft state to commit.
 */
function HourSelect({
  id,
  labelKey,
  value,
  disabled,
  onChange,
}: {
  id: string;
  labelKey: string;
  value: number;
  disabled: boolean;
  onChange: (hour: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs">
        {t(labelKey)}
      </Label>
      <Select
        value={String(value)}
        disabled={disabled}
        onValueChange={(next) => onChange(Number(next))}
      >
        <SelectTrigger id={id} className="w-28">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {HOURS.map((hour) => (
            <SelectItem key={hour} value={String(hour)}>
              {formatHour(hour)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
