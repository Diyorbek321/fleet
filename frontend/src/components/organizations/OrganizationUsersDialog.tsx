import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
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
import {
  ASSIGNABLE_ROLES,
  organizationsApi,
  type AssignableRole,
  type Organization,
  type OrgUserCreate,
} from '@/lib/api';

import { MIN_PASSWORD_LENGTH, describeError } from './shared';

const emptyForm = { email: '', password: '', role: 'manager' as AssignableRole };

interface OrganizationUsersDialogProps {
  /** The company whose logins are being managed; `null` closes the dialog. */
  target: Organization | null;
  onClose: () => void;
  onCreateUser: (orgId: string, body: OrgUserCreate) => void;
  isPending: boolean;
  /** Bumped by the parent after a successful create so the list refetches. */
  usersQueryKey: readonly unknown[];
}

export function OrganizationUsersDialog({
  target,
  onClose,
  onCreateUser,
  isPending,
  usersQueryKey,
}: OrganizationUsersDialogProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState(emptyForm);

  const usersQuery = useQuery({
    queryKey: usersQueryKey,
    queryFn: () => organizationsApi.listUsers(target!.id),
    enabled: target !== null,
  });

  // Clear the form whenever a different company is opened, and after the parent
  // reports a successful create (which flips isPending back to false).
  useEffect(() => {
    setForm(emptyForm);
  }, [target]);

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t('organizations.manageUsers')}: {target?.name}
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
            if (!target) return;
            onCreateUser(target.id, {
              email: form.email.trim(),
              password: form.password,
              role: form.role,
            });
            setForm(emptyForm);
          }}
        >
          <p className="text-sm font-medium">{t('organizations.addUser')}</p>
          <div className="space-y-2">
            <Label htmlFor="org-user-email">{t('users.email')}</Label>
            <Input
              id="org-user-email"
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="org-user-password">{t('users.password')}</Label>
            <Input
              id="org-user-password"
              type="password"
              required
              minLength={MIN_PASSWORD_LENGTH}
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">{t('users.passwordHint')}</p>
          </div>
          <div className="space-y-2">
            <Label>{t('users.role')}</Label>
            <Select
              value={form.role}
              onValueChange={(v) => setForm({ ...form, role: v as AssignableRole })}
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
          <Button type="submit" disabled={isPending}>
            <Plus className="mr-2 h-4 w-4" />
            {t('common.add')}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
