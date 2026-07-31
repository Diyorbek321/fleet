/**
 * The platform operator's company console.
 *
 * This is the only screen that crosses tenant boundaries, and it is deliberately
 * the *management* surface only: it onboards, suspends and deletes customer
 * companies and their staff logins, but never shows their fleet data. Everything
 * here is gated behind `superadmin` by the route guard, not by this component.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Ban, Pencil, Play, Plus, Search, Trash2, Users } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
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
import { Textarea } from '@/components/ui/textarea';
import {
  ASSIGNABLE_ROLES,
  ApiError,
  organizationsApi,
  type AssignableRole,
  type Organization,
} from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from '@/hooks/use-toast';

const ORGS_KEY = 'organizations';

/** Backend minimum for every password field on this screen; mirrored client-side. */
const MIN_PASSWORD_LENGTH = 8;

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

const emptyCreateForm = {
  name: '',
  admin_email: '',
  admin_password: '',
  contact_name: '',
  contact_phone: '',
  notes: '',
};

const emptyUserForm = {
  email: '',
  password: '',
  role: 'manager' as AssignableRole,
};

export default function OrganizationsPage() {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState(emptyCreateForm);
  /** Set once a company is created so the dialog can hand the login over to the operator. */
  const [createdAdminEmail, setCreatedAdminEmail] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<Organization | null>(null);
  const [editForm, setEditForm] = useState({
    name: '',
    contact_name: '',
    contact_phone: '',
    notes: '',
  });

  const [toggleTarget, setToggleTarget] = useState<Organization | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Organization | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState('');

  const [usersTarget, setUsersTarget] = useState<Organization | null>(null);
  const [userForm, setUserForm] = useState(emptyUserForm);

  // Debounced so typing a company name doesn't fire a request per keystroke: the
  // backend does a name scan for ?q= over the operator's whole book of business.
  useEffect(() => {
    const handle = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(handle);
  }, [search]);

  const orgsQuery = useQuery({
    queryKey: [ORGS_KEY, query],
    queryFn: () => organizationsApi.list(query || undefined),
  });

  const usersQuery = useQuery({
    queryKey: [ORGS_KEY, usersTarget?.id, 'users'],
    queryFn: () => organizationsApi.listUsers(usersTarget!.id),
    enabled: usersTarget !== null,
  });

  const invalidateOrgs = () => queryClient.invalidateQueries({ queryKey: [ORGS_KEY] });

  /** Every failure surfaces the server's own detail — a silent no-op here would
   *  leave the operator believing a customer was provisioned when it wasn't. */
  const failed = (titleKey: string) => (err: unknown) =>
    toast({ title: t(titleKey), description: describeError(err, ''), variant: 'destructive' });

  const createMutation = useMutation({
    mutationFn: organizationsApi.create,
    onSuccess: (org) => {
      setCreatedAdminEmail(createForm.admin_email.trim());
      setCreateForm(emptyCreateForm);
      invalidateOrgs();
      toast({ title: t('organizations.created'), description: org.name });
    },
    onError: failed('organizations.saveFailed'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Parameters<typeof organizationsApi.update>[1]) =>
      organizationsApi.update(id, body),
    onSuccess: () => {
      setEditTarget(null);
      setToggleTarget(null);
      invalidateOrgs();
      toast({ title: t('organizations.updated') });
    },
    onError: failed('organizations.saveFailed'),
  });

  const deleteMutation = useMutation({
    mutationFn: ({ id, confirm }: { id: string; confirm: string }) =>
      organizationsApi.remove(id, confirm),
    onSuccess: () => {
      setDeleteTarget(null);
      setDeleteConfirm('');
      invalidateOrgs();
      toast({ title: t('organizations.deleted') });
    },
    onError: failed('organizations.deleteFailed'),
  });

  const createUserMutation = useMutation({
    mutationFn: ({ orgId, ...body }: { orgId: string } & typeof emptyUserForm) =>
      organizationsApi.createUser(orgId, body),
    onSuccess: () => {
      setUserForm(emptyUserForm);
      queryClient.invalidateQueries({ queryKey: [ORGS_KEY, usersTarget?.id, 'users'] });
      invalidateOrgs();
      toast({ title: t('organizations.userCreated') });
    },
    onError: failed('organizations.saveFailed'),
  });

  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }),
    [i18n.language],
  );

  const organizations = orgsQuery.data ?? [];

  const openEdit = (org: Organization) => {
    setEditTarget(org);
    setEditForm({
      name: org.name,
      contact_name: org.contact_name ?? '',
      contact_phone: org.contact_phone ?? '',
      notes: org.notes ?? '',
    });
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('organizations.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('organizations.subtitle')}</p>
        </div>
        <Button
          onClick={() => {
            setCreatedAdminEmail(null);
            setCreateForm(emptyCreateForm);
            setCreateOpen(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" />
          {t('organizations.add')}
        </Button>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder={t('organizations.searchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {orgsQuery.isError && (
        <Card className="border-destructive/40">
          <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
            <AlertCircle className="h-4 w-4 text-destructive" />
            <span className="font-medium">{t('organizations.loadFailed')}</span>
            <span className="text-muted-foreground">{describeError(orgsQuery.error, '')}</span>
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              onClick={() => void orgsQuery.refetch()}
            >
              {t('common.search')}
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="rounded-lg border border-border bg-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('organizations.name')}</TableHead>
              <TableHead>{t('organizations.contactName')}</TableHead>
              <TableHead className="text-right">{t('organizations.userCount')}</TableHead>
              <TableHead className="text-right">{t('organizations.truckCount')}</TableHead>
              <TableHead className="text-right">{t('organizations.driverCount')}</TableHead>
              <TableHead className="text-right">{t('organizations.tripCount')}</TableHead>
              <TableHead>{t('organizations.createdAt')}</TableHead>
              <TableHead>{t('organizations.status')}</TableHead>
              <TableHead className="w-[1%]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {orgsQuery.isLoading && (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {!orgsQuery.isLoading && !orgsQuery.isError && organizations.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                  {t('organizations.empty')}
                </TableCell>
              </TableRow>
            )}
            {organizations.map((org) => (
              <TableRow key={org.id} className={org.is_active ? undefined : 'opacity-60'}>
                <TableCell className="font-medium">{org.name}</TableCell>
                <TableCell>
                  <div className="flex flex-col">
                    <span>{org.contact_name ?? '—'}</span>
                    {org.contact_phone && (
                      <span className="text-xs text-muted-foreground">{org.contact_phone}</span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">{org.user_count}</TableCell>
                <TableCell className="text-right tabular-nums">{org.truck_count}</TableCell>
                <TableCell className="text-right tabular-nums">{org.driver_count}</TableCell>
                <TableCell className="text-right tabular-nums">{org.trip_count}</TableCell>
                <TableCell className="text-muted-foreground">
                  {dateFmt.format(new Date(org.created_at))}
                </TableCell>
                <TableCell>
                  <Badge variant={org.is_active ? 'default' : 'secondary'}>
                    {org.is_active ? t('organizations.active') : t('organizations.suspended')}
                  </Badge>
                </TableCell>
                <TableCell className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    title={t('organizations.manageUsers')}
                    onClick={() => {
                      setUsersTarget(org);
                      setUserForm(emptyUserForm);
                    }}
                  >
                    <Users className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    title={t('common.edit')}
                    onClick={() => openEdit(org)}
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    title={org.is_active ? t('organizations.suspend') : t('organizations.activate')}
                    onClick={() => setToggleTarget(org)}
                  >
                    {org.is_active ? <Ban className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </Button>
                  {/* The backend refuses to delete the caller's own org; disabling the
                      button keeps that rule visible instead of only in an error toast. */}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive"
                    title={t('common.delete')}
                    disabled={org.id === user?.org_id}
                    onClick={() => {
                      setDeleteTarget(org);
                      setDeleteConfirm('');
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Create company */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('organizations.add')}</DialogTitle>
          </DialogHeader>
          {createdAdminEmail ? (
            // Success state: the operator has to hand this login to the customer,
            // so it stays on screen until they explicitly dismiss it.
            <div className="space-y-4">
              <p className="text-sm font-medium">{t('organizations.created')}</p>
              <div className="rounded-md border border-border bg-muted/40 p-3">
                <p className="text-xs text-muted-foreground">{t('organizations.adminEmail')}</p>
                <p className="font-mono text-sm">{createdAdminEmail}</p>
              </div>
              <DialogFooter>
                <Button
                  onClick={() => {
                    setCreatedAdminEmail(null);
                    setCreateOpen(false);
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
                createMutation.mutate({
                  name: createForm.name.trim(),
                  admin_email: createForm.admin_email.trim(),
                  admin_password: createForm.admin_password,
                  contact_name: createForm.contact_name.trim() || null,
                  contact_phone: createForm.contact_phone.trim() || null,
                  notes: createForm.notes.trim() || null,
                });
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="org-name">{t('organizations.name')}</Label>
                <Input
                  id="org-name"
                  required
                  value={createForm.name}
                  onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="org-contact">{t('organizations.contactName')}</Label>
                  <Input
                    id="org-contact"
                    value={createForm.contact_name}
                    onChange={(e) => setCreateForm({ ...createForm, contact_name: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="org-phone">{t('organizations.contactPhone')}</Label>
                  <Input
                    id="org-phone"
                    value={createForm.contact_phone}
                    onChange={(e) => setCreateForm({ ...createForm, contact_phone: e.target.value })}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="org-notes">{t('organizations.notes')}</Label>
                <Textarea
                  id="org-notes"
                  rows={2}
                  value={createForm.notes}
                  onChange={(e) => setCreateForm({ ...createForm, notes: e.target.value })}
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
                    value={createForm.admin_email}
                    onChange={(e) => setCreateForm({ ...createForm, admin_email: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="org-admin-password">{t('organizations.adminPassword')}</Label>
                  <Input
                    id="org-admin-password"
                    type="password"
                    required
                    minLength={MIN_PASSWORD_LENGTH}
                    value={createForm.admin_password}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, admin_password: e.target.value })
                    }
                  />
                  <p className="text-xs text-muted-foreground">{t('organizations.passwordHint')}</p>
                </div>
              </div>

              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
                  {t('common.cancel')}
                </Button>
                <Button type="submit" disabled={createMutation.isPending}>
                  {t('common.save')}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* Edit company */}
      <Dialog open={editTarget !== null} onOpenChange={(open) => !open && setEditTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editTarget?.name}</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!editTarget) return;
              updateMutation.mutate({
                id: editTarget.id,
                name: editForm.name.trim(),
                contact_name: editForm.contact_name.trim() || null,
                contact_phone: editForm.contact_phone.trim() || null,
                notes: editForm.notes.trim() || null,
              });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="edit-name">{t('organizations.name')}</Label>
              <Input
                id="edit-name"
                required
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="edit-contact">{t('organizations.contactName')}</Label>
                <Input
                  id="edit-contact"
                  value={editForm.contact_name}
                  onChange={(e) => setEditForm({ ...editForm, contact_name: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-phone">{t('organizations.contactPhone')}</Label>
                <Input
                  id="edit-phone"
                  value={editForm.contact_phone}
                  onChange={(e) => setEditForm({ ...editForm, contact_phone: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-notes">{t('organizations.notes')}</Label>
              <Textarea
                id="edit-notes"
                rows={3}
                value={editForm.notes}
                onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">{t('organizations.notesHint')}</p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEditTarget(null)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Suspend / reactivate */}
      <Dialog open={toggleTarget !== null} onOpenChange={(open) => !open && setToggleTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {toggleTarget?.is_active ? t('organizations.suspend') : t('organizations.activate')}:{' '}
              {toggleTarget?.name}
            </DialogTitle>
            <DialogDescription>{t('organizations.suspendHint')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToggleTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant={toggleTarget?.is_active ? 'destructive' : 'default'}
              disabled={updateMutation.isPending}
              onClick={() => {
                if (!toggleTarget) return;
                updateMutation.mutate({ id: toggleTarget.id, is_active: !toggleTarget.is_active });
              }}
            >
              {toggleTarget?.is_active ? t('organizations.suspend') : t('organizations.activate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete — typed-name confirmation, mirroring the backend's ?confirm= guard */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
            setDeleteConfirm('');
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t('organizations.deleteTitle')}: {deleteTarget?.name}
            </DialogTitle>
            <DialogDescription>{t('organizations.deleteWarning')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="delete-confirm">{t('organizations.deleteConfirmLabel')}</Label>
            <Input
              id="delete-confirm"
              value={deleteConfirm}
              onChange={(e) => setDeleteConfirm(e.target.value)}
            />
            {deleteConfirm.length > 0 && deleteConfirm !== deleteTarget?.name && (
              <p className="text-xs text-destructive">{t('organizations.deleteConfirmMismatch')}</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending || deleteConfirm !== deleteTarget?.name}
              onClick={() => {
                if (!deleteTarget) return;
                deleteMutation.mutate({ id: deleteTarget.id, confirm: deleteConfirm });
              }}
            >
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Drill-in: this company's staff logins */}
      <Dialog open={usersTarget !== null} onOpenChange={(open) => !open && setUsersTarget(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {t('organizations.manageUsers')}: {usersTarget?.name}
            </DialogTitle>
          </DialogHeader>

          {usersQuery.isLoading && (
            <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
          )}
          {usersQuery.isError && (
            <p className="text-sm text-destructive">
              {t('users.loadFailed')}: {describeError(usersQuery.error, '')}
            </p>
          )}
          {usersQuery.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('organizations.noUsers')}</p>
          )}
          {usersQuery.data && usersQuery.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('users.email')}</TableHead>
                  <TableHead>{t('users.role')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usersQuery.data.map((orgUser) => (
                  <TableRow key={orgUser.id}>
                    <TableCell className="font-mono text-xs">{orgUser.email}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{t(`users.roles.${orgUser.role}`)}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          <form
            className="space-y-3 rounded-md border border-border p-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!usersTarget) return;
              createUserMutation.mutate({
                orgId: usersTarget.id,
                email: userForm.email.trim(),
                password: userForm.password,
                role: userForm.role,
              });
            }}
          >
            <p className="text-sm font-medium">{t('organizations.addUser')}</p>
            <div className="space-y-2">
              <Label htmlFor="org-user-email">{t('users.email')}</Label>
              <Input
                id="org-user-email"
                type="email"
                required
                value={userForm.email}
                onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="org-user-password">{t('users.password')}</Label>
              <Input
                id="org-user-password"
                type="password"
                required
                minLength={MIN_PASSWORD_LENGTH}
                value={userForm.password}
                onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">{t('users.passwordHint')}</p>
            </div>
            <div className="space-y-2">
              <Label>{t('users.role')}</Label>
              <Select
                value={userForm.role}
                onValueChange={(v) => setUserForm({ ...userForm, role: v as AssignableRole })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ASSIGNABLE_ROLES.map((role) => (
                    <SelectItem key={role} value={role}>
                      {t(`users.roles.${role}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">{t('users.driverHint')}</p>
            </div>
            <Button type="submit" disabled={createUserMutation.isPending}>
              <Plus className="mr-2 h-4 w-4" />
              {t('common.add')}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
