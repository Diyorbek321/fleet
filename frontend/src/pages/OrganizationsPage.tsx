/**
 * The platform operator's company console.
 *
 * This is the only screen that crosses tenant boundaries, and it is deliberately
 * the *management* surface only: it onboards, suspends and deletes customer
 * companies and their staff logins, but never shows their fleet data. Everything
 * here is gated behind `superadmin` by the route guard, not by this component.
 *
 * The page owns the data (queries, mutations, toasts) and which dialog is open;
 * the table and the five dialogs live in `@/components/organizations` and keep
 * their own form state.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Plus, Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { CreateOrganizationDialog } from '@/components/organizations/CreateOrganizationDialog';
import { DeleteOrganizationDialog } from '@/components/organizations/DeleteOrganizationDialog';
import { EditOrganizationDialog } from '@/components/organizations/EditOrganizationDialog';
import { OrganizationUsersDialog } from '@/components/organizations/OrganizationUsersDialog';
import { OrganizationsTable } from '@/components/organizations/OrganizationsTable';
import { ToggleOrganizationDialog } from '@/components/organizations/ToggleOrganizationDialog';
import { describeError } from '@/components/organizations/shared';
import {
  organizationsApi,
  type Organization,
  type OrganizationCreate,
  type OrganizationUpdate,
  type OrgUserCreate,
} from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from '@/hooks/use-toast';

const ORGS_KEY = 'organizations';

export default function OrganizationsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');

  const [createOpen, setCreateOpen] = useState(false);
  /** Set once a company is created so the dialog can hand the login over to the operator. */
  const [createdAdminEmail, setCreatedAdminEmail] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<Organization | null>(null);
  const [toggleTarget, setToggleTarget] = useState<Organization | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Organization | null>(null);
  const [usersTarget, setUsersTarget] = useState<Organization | null>(null);

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

  const usersQueryKey = [ORGS_KEY, usersTarget?.id, 'users'] as const;

  const invalidateOrgs = () => queryClient.invalidateQueries({ queryKey: [ORGS_KEY] });

  /** Every failure surfaces the server's own detail — a silent no-op here would
   *  leave the operator believing a customer was provisioned when it wasn't. */
  const failed = (titleKey: string) => (err: unknown) =>
    toast({ title: t(titleKey), description: describeError(err, ''), variant: 'destructive' });

  const createMutation = useMutation({
    mutationFn: organizationsApi.create,
    onSuccess: (org, variables: OrganizationCreate) => {
      setCreatedAdminEmail(variables.admin_email);
      invalidateOrgs();
      toast({ title: t('organizations.created'), description: org.name });
    },
    onError: failed('organizations.saveFailed'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...body }: { id: string } & OrganizationUpdate) =>
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
      invalidateOrgs();
      toast({ title: t('organizations.deleted') });
    },
    onError: failed('organizations.deleteFailed'),
  });

  const createUserMutation = useMutation({
    mutationFn: ({ orgId, ...body }: { orgId: string } & OrgUserCreate) =>
      organizationsApi.createUser(orgId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: usersQueryKey });
      invalidateOrgs();
      toast({ title: t('organizations.userCreated') });
    },
    onError: failed('organizations.saveFailed'),
  });

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

      <OrganizationsTable
        organizations={orgsQuery.data ?? []}
        isLoading={orgsQuery.isLoading}
        isError={orgsQuery.isError}
        currentOrgId={user?.org_id}
        onManageUsers={setUsersTarget}
        onEdit={setEditTarget}
        onToggleActive={setToggleTarget}
        onDelete={setDeleteTarget}
      />

      <CreateOrganizationDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={(body) => createMutation.mutate(body)}
        isPending={createMutation.isPending}
        createdAdminEmail={createdAdminEmail}
        onDismissSuccess={() => setCreatedAdminEmail(null)}
      />

      <EditOrganizationDialog
        target={editTarget}
        onClose={() => setEditTarget(null)}
        onSubmit={(id, body) => updateMutation.mutate({ id, ...body })}
        isPending={updateMutation.isPending}
      />

      <ToggleOrganizationDialog
        target={toggleTarget}
        onClose={() => setToggleTarget(null)}
        onConfirm={(org) => updateMutation.mutate({ id: org.id, is_active: !org.is_active })}
        isPending={updateMutation.isPending}
      />

      <DeleteOrganizationDialog
        target={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={(org, confirm) => deleteMutation.mutate({ id: org.id, confirm })}
        isPending={deleteMutation.isPending}
      />

      <OrganizationUsersDialog
        target={usersTarget}
        onClose={() => setUsersTarget(null)}
        onCreateUser={(orgId, body) => createUserMutation.mutate({ orgId, ...body })}
        isPending={createUserMutation.isPending}
        usersQueryKey={usersQueryKey}
      />
    </div>
  );
}
