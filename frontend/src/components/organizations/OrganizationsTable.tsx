import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Ban, Eye, Pencil, Play, Trash2, Users } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { Organization } from '@/lib/api';
import { startSupportSession } from '@/components/SupportSessionBanner';

interface OrganizationsTableProps {
  organizations: Organization[];
  isLoading: boolean;
  isError: boolean;
  /** Used to disable "delete" on the operator's own company. */
  currentOrgId?: string;
  onManageUsers: (org: Organization) => void;
  onEdit: (org: Organization) => void;
  onToggleActive: (org: Organization) => void;
  onDelete: (org: Organization) => void;
}

const COLUMN_COUNT = 9;

export function OrganizationsTable({
  organizations,
  isLoading,
  isError,
  currentOrgId,
  onManageUsers,
  onEdit,
  onToggleActive,
  onDelete,
}: OrganizationsTableProps) {
  const { t, i18n } = useTranslation();
  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }),
    [i18n.language],
  );

  return (
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
          {isLoading && (
            <TableRow>
              <TableCell colSpan={COLUMN_COUNT} className="py-8 text-center text-muted-foreground">
                {t('common.loading')}
              </TableCell>
            </TableRow>
          )}
          {!isLoading && !isError && organizations.length === 0 && (
            <TableRow>
              <TableCell colSpan={COLUMN_COUNT} className="py-8 text-center text-muted-foreground">
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
                  // Only for a customer, never for the operator's own
                  // organization: "view as support" on yourself is the screens
                  // you are already looking at, and the audit row it writes
                  // would be noise.
                  disabled={org.id === currentOrgId}
                  title={t('support.viewHint')}
                  onClick={() => startSupportSession(org.id, org.name)}
                >
                  <Eye className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  title={t('organizations.manageUsers')}
                  onClick={() => onManageUsers(org)}
                >
                  <Users className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  title={t('common.edit')}
                  onClick={() => onEdit(org)}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  title={org.is_active ? t('organizations.suspend') : t('organizations.activate')}
                  onClick={() => onToggleActive(org)}
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
                  disabled={org.id === currentOrgId}
                  onClick={() => onDelete(org)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
