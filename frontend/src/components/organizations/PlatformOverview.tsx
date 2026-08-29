import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Activity, ScrollText } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { organizationsApi } from '@/lib/api';

/**
 * The operator's own two screens: the book of business, and what we did to it.
 *
 * The per-company table below this answers "how is this customer doing".
 * Neither of these can be got from it — nobody adds up a paginated table in
 * their head, and nothing in the customer-facing product records that their
 * account was suspended at 14:02 by a particular person.
 */
export function PlatformOverview() {
  const { t } = useTranslation();

  const stats = useQuery({
    queryKey: ['platform', 'stats'],
    queryFn: organizationsApi.platformStats,
  });
  const audit = useQuery({
    queryKey: ['platform', 'audit'],
    queryFn: () => organizationsApi.auditLog(),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="border-border/50 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4" /> {t('platform.title')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label={t('platform.organizations')} value={stats.data?.organizations} />
            <Stat
              label={t('platform.active')}
              value={stats.data?.active_organizations}
              tone="good"
            />
            <Stat
              label={t('platform.suspended')}
              value={stats.data?.suspended_organizations}
              // Only coloured when there is one. A permanent red zero trains
              // the eye to ignore the number that matters when it changes.
              tone={stats.data?.suspended_organizations ? 'bad' : undefined}
            />
            <Stat label={t('platform.trucks')} value={stats.data?.trucks} />
            <Stat label={t('platform.drivers')} value={stats.data?.drivers} />
            <Stat label={t('platform.users')} value={stats.data?.users} />
            <Stat label={t('platform.trips')} value={stats.data?.trips} />
            <Stat label={t('platform.trips30')} value={stats.data?.trips_last_30d} />
            <Stat label={t('platform.gpsPoints')} value={stats.data?.gps_points} />
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/50 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ScrollText className="h-4 w-4" /> {t('platform.audit')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-72 overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('platform.when')}</TableHead>
                  <TableHead>{t('platform.action')}</TableHead>
                  <TableHead>{t('platform.target')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(audit.data ?? []).length === 0 && (
                  <TableRow>
                    <TableCell colSpan={3} className="py-6 text-center text-muted-foreground">
                      {t('platform.auditEmpty')}
                    </TableCell>
                  </TableRow>
                )}
                {(audit.data ?? []).map((event) => (
                  <TableRow key={event.id}>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {new Date(event.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-sm">
                      <div className="font-medium">{event.action}</div>
                      {event.detail && (
                        <div className="text-xs text-muted-foreground">{event.detail}</div>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">
                      {/* The name, not the id: after a deletion the id refers
                          to nothing, which is when this row matters most. */}
                      <div>{event.target_org_name ?? '—'}</div>
                      <div className="text-xs text-muted-foreground">{event.actor_email}</div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | undefined;
  tone?: 'good' | 'bad';
}) {
  const colour = tone === 'good' ? 'text-emerald-600' : tone === 'bad' ? 'text-destructive' : '';
  return (
    <div className="rounded-lg border border-border/50 p-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold ${colour}`}>
        {value === undefined ? '—' : value.toLocaleString()}
      </div>
    </div>
  );
}
