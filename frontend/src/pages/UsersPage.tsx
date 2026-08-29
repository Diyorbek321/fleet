import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, Plus, Trash2, UserCog } from 'lucide-react';

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
import { Badge } from '@/components/ui/badge';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  ApiError,
  ASSIGNABLE_ROLES,
  usersApi,
  type AssignableRole,
  type OrgUser,
  type UserRole,
} from '@/lib/api';
import { driversApi } from '@/lib/drivers';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from '@/hooks/use-toast';

const USERS_KEY = ['org-users'] as const;
const DRIVERS_KEY = ['drivers'] as const;

/** Surface the server's own `detail` — a generic message hides real causes such as
 *  "Email already registered" or "Cannot demote yourself". */
function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

/** Admins run the company, so they read as the "primary" badge; drivers are
 *  read-only rows here (they are managed on the Drivers page) so they stay muted. */
function roleBadgeVariant(role: UserRole): 'default' | 'secondary' | 'outline' {
  if (role === 'admin' || role === 'superadmin') return 'default';
  if (role === 'driver') return 'outline';
  return 'secondary';
}

const EMPTY_INVITE = { email: '', password: '', role: 'manager' as AssignableRole };

export default function UsersPage() {
  const { t } = useTranslation();
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();

  const [inviteOpen, setInviteOpen] = useState(false);
  const [invite, setInvite] = useState(EMPTY_INVITE);
  const [roleTarget, setRoleTarget] = useState<OrgUser | null>(null);
  const [nextRole, setNextRole] = useState<AssignableRole>('manager');
  const [passwordTarget, setPasswordTarget] = useState<OrgUser | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<OrgUser | null>(null);

  const {
    data: users = [],
    isLoading,
    error,
  } = useQuery({ queryKey: USERS_KEY, queryFn: usersApi.list });

  // `OrgUser` carries no driver_id, so a driver account is recognised by matching
  // its login e-mail against the org's driver profiles. That is exactly the link
  // the backend creates in POST /api/drivers, and it costs one cached request
  // instead of a per-row lookup.
  const { data: drivers = [] } = useQuery({ queryKey: DRIVERS_KEY, queryFn: driversApi.list });

  const driverNameByEmail = useMemo(() => {
    const out: Record<string, string> = {};
    for (const d of drivers) {
      if (d.email) out[d.email.toLowerCase()] = d.name;
    }
    return out;
  }, [drivers]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: USERS_KEY });

  const failToast = (titleKey: string) => (err: unknown) =>
    toast({ title: t(titleKey), description: describeError(err, ''), variant: 'destructive' });

  const createMutation = useMutation({
    mutationFn: usersApi.create,
    onSuccess: () => {
      setInviteOpen(false);
      setInvite(EMPTY_INVITE);
      invalidate();
      toast({ title: t('users.created') });
    },
    onError: failToast('users.saveFailed'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, role, password }: { id: string; role?: AssignableRole; password?: string }) =>
      usersApi.update(id, { role, password }),
    onSuccess: () => {
      setRoleTarget(null);
      setPasswordTarget(null);
      setNewPassword('');
      invalidate();
      toast({ title: t('users.updated') });
    },
    onError: failToast('users.saveFailed'),
  });

  const removeMutation = useMutation({
    mutationFn: usersApi.remove,
    onSuccess: () => {
      setDeleteTarget(null);
      invalidate();
      toast({ title: t('users.deleted') });
    },
    onError: failToast('users.deleteFailed'),
  });

  const roleLabel = (role: UserRole) => t(`users.roles.${role}`);

  /** Mirrors the backend's 400s: you may not demote or delete yourself, and a
   *  driver's role is owned by its Driver profile. */
  const lockReason = (u: OrgUser, forDelete: boolean): string | null => {
    if (currentUser && u.id === currentUser.id) {
      return forDelete ? t('users.cannotDeleteSelf') : t('users.cannotEditSelf');
    }
    if (!forDelete && u.role === 'driver') return t('users.driverHint');
    return null;
  };

  const renderAction = (
    u: OrgUser,
    icon: JSX.Element,
    label: string,
    onClick: () => void,
    forDelete: boolean,
  ) => {
    const reason = lockReason(u, forDelete);
    const button = (
      <Button
        variant="ghost"
        size="icon"
        title={reason ?? label}
        aria-label={label}
        disabled={reason !== null}
        className={forDelete ? 'text-destructive hover:text-destructive' : undefined}
        onClick={onClick}
      >
        {icon}
      </Button>
    );
    if (!reason) return button;
    // A disabled button swallows pointer events, so the trigger has to be a wrapper.
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex">{button}</span>
        </TooltipTrigger>
        <TooltipContent>{reason}</TooltipContent>
      </Tooltip>
    );
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('users.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('users.subtitle')}</p>
        </div>
        <Button onClick={() => setInviteOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('users.add')}
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('users.email')}</TableHead>
              <TableHead>{t('users.role')}</TableHead>
              <TableHead>{t('drivers.title')}</TableHead>
              <TableHead className="w-[1%]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {!isLoading && error && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-destructive py-8">
                  {t('users.loadFailed')}
                  <span className="block text-xs text-muted-foreground">
                    {describeError(error, '')}
                  </span>
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !error && users.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                  {t('users.empty')}
                </TableCell>
              </TableRow>
            )}
            {users.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-medium">
                  {u.email}
                  {currentUser?.id === u.id && (
                    <span className="ml-2 text-xs text-muted-foreground">({t('users.you')})</span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={roleBadgeVariant(u.role)}>{roleLabel(u.role)}</Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {driverNameByEmail[u.email.toLowerCase()] ?? '—'}
                </TableCell>
                <TableCell className="flex gap-1">
                  {renderAction(
                    u,
                    <UserCog className="h-4 w-4" />,
                    t('users.role'),
                    () => {
                      setRoleTarget(u);
                      setNextRole(
                        ASSIGNABLE_ROLES.includes(u.role as AssignableRole)
                          ? (u.role as AssignableRole)
                          : 'manager',
                      );
                    },
                    false,
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    title={t('users.changePassword')}
                    aria-label={t('users.changePassword')}
                    onClick={() => {
                      setPasswordTarget(u);
                      setNewPassword('');
                    }}
                  >
                    <KeyRound className="h-4 w-4" />
                  </Button>
                  {renderAction(
                    u,
                    <Trash2 className="h-4 w-4" />,
                    t('common.delete'),
                    () => setDeleteTarget(u),
                    true,
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Invite dialog */}
      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('users.add')}</DialogTitle>
            <DialogDescription>{t('users.driverHint')}</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate({
                email: invite.email.trim(),
                password: invite.password,
                role: invite.role,
              });
            }}
            className="space-y-3"
          >
            <div className="space-y-2">
              <Label htmlFor="u-email">{t('users.email')}</Label>
              <Input
                id="u-email"
                type="email"
                required
                value={invite.email}
                onChange={(e) => setInvite({ ...invite, email: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="u-password">{t('users.password')}</Label>
              <Input
                id="u-password"
                type="password"
                required
                minLength={8}
                value={invite.password}
                onChange={(e) => setInvite({ ...invite, password: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">{t('users.passwordHint')}</p>
            </div>
            <div className="space-y-2">
              <Label>{t('users.role')}</Label>
              <Select
                value={invite.role}
                onValueChange={(v) => setInvite({ ...invite, role: v as AssignableRole })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ASSIGNABLE_ROLES.map((r) => (
                    <SelectItem key={r} value={r}>
                      {roleLabel(r)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setInviteOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Change role dialog */}
      <Dialog open={roleTarget !== null} onOpenChange={(open) => !open && setRoleTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('users.role')}</DialogTitle>
            <DialogDescription>{roleTarget?.email}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label>{t('users.role')}</Label>
            <Select value={nextRole} onValueChange={(v) => setNextRole(v as AssignableRole)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ASSIGNABLE_ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {roleLabel(r)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              disabled={updateMutation.isPending || roleTarget?.role === nextRole}
              onClick={() => {
                if (roleTarget) updateMutation.mutate({ id: roleTarget.id, role: nextRole });
              }}
            >
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reset password dialog */}
      <Dialog
        open={passwordTarget !== null}
        onOpenChange={(open) => !open && setPasswordTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('users.changePassword')}</DialogTitle>
            <DialogDescription>{passwordTarget?.email}</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (passwordTarget) {
                updateMutation.mutate({ id: passwordTarget.id, password: newPassword });
              }
            }}
            className="space-y-3"
          >
            <div className="space-y-2">
              <Label htmlFor="u-new-password">{t('users.newPassword')}</Label>
              <Input
                id="u-new-password"
                type="password"
                required
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{t('users.passwordHint')}</p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setPasswordTarget(null)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('users.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>{deleteTarget?.email}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              disabled={removeMutation.isPending}
              onClick={(e) => {
                // Keep the dialog mounted until the request settles so an error
                // toast is not the only trace of a failed delete.
                e.preventDefault();
                if (deleteTarget) removeMutation.mutate(deleteTarget.id);
              }}
            >
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
