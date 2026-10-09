/**
 * Every paper that can stop a rig at a border, on one screen, in two tabs.
 *
 * "Truck": the insurance policy per country (UZ, KZ, RU), then technical
 * inspection, permit, transport licence, certificate and tachograph.
 * "Driver": foreign passport, certificate, chip card, licence and passport.
 * Each is one expiry date, editable in place.
 *
 * The insurance and licence dates already drive the reminders — the driver's
 * phone and the owner's Telegram are warned a month out, a week out and on the
 * day — but a reminder says one thing about one truck. This is where the
 * dispatcher sees the whole fleet at once and types in the new date when a
 * document is renewed.
 */
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, ShieldCheck, ShieldQuestion, Search, Truck as TruckIcon, User } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DocumentDateCell } from '@/components/documents/DocumentDateCell';
import { useTrucks } from '@/contexts/TruckContext';
import { ApiError } from '@/lib/api';
import {
  DRIVER_COLUMNS,
  TRUCK_COLUMNS,
  needsAttention,
  nearestDocumentDays,
  summarizeDocuments,
  type DocumentColumn,
} from '@/lib/documents';
import { driversApi, type Driver, type DriverDocumentField } from '@/lib/drivers';
import { localToday } from '@/lib/insurance';
import { toast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';

type SortMode = 'list' | 'urgent';
type FilterMode = 'all' | 'attention';
type Tab = 'trucks' | 'drivers';

/** One row of either table, reduced to what the table needs. */
interface DocumentRow {
  id: string;
  title: string;
  subtitle?: string;
  dimmed: boolean;
  dates: Partial<Record<string, string | null | undefined>>;
  href: string;
}

function pickDates<F extends string>(
  source: { [K in F]?: string | null },
  cols: readonly DocumentColumn<F>[],
): DocumentRow['dates'] {
  return Object.fromEntries(cols.map(({ field }) => [field, source[field]]));
}

function SummaryCard({
  icon: Icon,
  value,
  label,
  className,
}: {
  icon: typeof ShieldAlert;
  value: number;
  label: string;
  className: string;
}) {
  return (
    <Card className="border-border/50 bg-card">
      <CardContent className="flex items-center gap-3 p-4">
        <div className={cn('flex h-10 w-10 items-center justify-center rounded-lg', className)}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <div className="text-2xl font-bold leading-none">{value}</div>
          <div className="mt-1 text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function useDriverDocuments() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['drivers'], queryFn: driversApi.list });
  const mutation = useMutation({
    mutationFn: ({ id, field, value }: { id: string; field: DriverDocumentField; value: string | null }) =>
      driversApi.update(id, { [field]: value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drivers'] });
      toast({ title: t('drivers.updated') });
    },
    onError: (err) =>
      toast({
        title: t('drivers.saveFailed'),
        description: err instanceof ApiError ? err.detail : String(err),
        variant: 'destructive',
      }),
  });
  return { drivers: query.data ?? [], isLoading: query.isLoading, update: mutation.mutate };
}

export default function InsurancePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { trucks, isLoading: trucksLoading, updateTruck } = useTrucks();
  const { drivers, isLoading: driversLoading, update: updateDriver } = useDriverDocuments();
  const [tab, setTab] = useState<Tab>('trucks');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortMode>('list');
  const [filter, setFilter] = useState<FilterMode>('all');
  const today = localToday();

  const columns: readonly DocumentColumn<string>[] = tab === 'trucks' ? TRUCK_COLUMNS : DRIVER_COLUMNS;
  const isLoading = tab === 'trucks' ? trucksLoading : driversLoading;

  const allRows = useMemo<DocumentRow[]>(
    () =>
      tab === 'trucks'
        ? trucks.map((truck) => ({
            id: truck.id,
            title: truck.plateNumber,
            subtitle: truck.name !== truck.plateNumber ? truck.name : undefined,
            dimmed: !truck.isEnabled,
            dates: pickDates(truck, TRUCK_COLUMNS),
            href: `/trucks/${truck.id}`,
          }))
        : drivers.map((driver: Driver) => ({
            id: driver.id,
            title: driver.name,
            subtitle: driver.passportNumber ?? undefined,
            dimmed: driver.status !== 'active',
            dates: pickDates(driver, DRIVER_COLUMNS),
            href: `/drivers/${driver.id}`,
          })),
    [tab, trucks, drivers],
  );

  const summary = useMemo(
    () => summarizeDocuments(allRows.map((r) => r.dates), columns, today),
    [allRows, columns, today],
  );

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = allRows.filter(
      (row) => !q || row.title.toLowerCase().includes(q) || (row.subtitle ?? '').toLowerCase().includes(q),
    );
    if (filter === 'attention') list = list.filter((row) => needsAttention(row.dates, columns, today));
    if (sort === 'urgent') {
      // Rows with no date at all go last: there is nothing to renew yet,
      // only something to fill in.
      list = [...list].sort(
        (a, b) =>
          (nearestDocumentDays(a.dates, columns, today) ?? Infinity) -
          (nearestDocumentDays(b.dates, columns, today) ?? Infinity),
      );
    }
    return list;
  }, [allRows, columns, search, filter, sort, today]);

  const commit = (row: DocumentRow, field: string, value: string | null) => {
    if (tab === 'trucks') void updateTruck(row.id, { [field]: value });
    else updateDriver({ id: row.id, field: field as DriverDocumentField, value });
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('insurance.title')}</h1>
        <p className="text-muted-foreground">{t('insurance.subtitle')}</p>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsList>
          <TabsTrigger value="trucks" className="gap-2">
            <TruckIcon className="h-4 w-4" />
            {t('documents.tabTrucks')}
          </TabsTrigger>
          <TabsTrigger value="drivers" className="gap-2">
            <User className="h-4 w-4" />
            {t('documents.tabDrivers')}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="grid gap-4 sm:grid-cols-3">
        <SummaryCard
          icon={ShieldAlert}
          value={summary.expired}
          label={t('documents.summary.expired')}
          className="bg-destructive/15 text-destructive"
        />
        <SummaryCard
          icon={ShieldCheck}
          value={summary.soon}
          label={t('insurance.summary.soon')}
          className="bg-status-stopped/20 text-status-stopped"
        />
        <SummaryCard
          icon={ShieldQuestion}
          value={summary.missing}
          label={t('insurance.summary.missing')}
          className="bg-muted text-muted-foreground"
        />
      </div>

      <Card className="border-border/50 bg-card">
        <CardContent className="flex flex-col gap-4 p-4 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={tab === 'trucks' ? t('insurance.searchPlaceholder') : t('documents.searchDrivers')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-secondary/50 border-0"
            />
          </div>
          <Select value={filter} onValueChange={(v) => setFilter(v as FilterMode)}>
            <SelectTrigger className="w-full sm:w-52 bg-secondary/50 border-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover">
              <SelectItem value="all">
                {tab === 'trucks' ? t('insurance.filter.all') : t('documents.filterAllDrivers')}
              </SelectItem>
              <SelectItem value="attention">{t('insurance.filter.attention')}</SelectItem>
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={(v) => setSort(v as SortMode)}>
            <SelectTrigger className="w-full sm:w-52 bg-secondary/50 border-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover">
              <SelectItem value="list">{t('insurance.sort.list')}</SelectItem>
              <SelectItem value="urgent">{t('insurance.sort.urgent')}</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card className="border-border/50 bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-border/50 hover:bg-transparent">
                <TableHead className="sticky left-0 z-10 bg-card text-muted-foreground">
                  {tab === 'trucks' ? t('trucks.colTruck') : t('drivers.name')}
                </TableHead>
                {columns.map(({ field, labelKey }) => (
                  <TableHead key={field} className="whitespace-nowrap text-muted-foreground">
                    {t(labelKey)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={columns.length + 1} className="py-12 text-center text-muted-foreground">
                    {t('common.loading')}
                  </TableCell>
                </TableRow>
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={columns.length + 1} className="py-12 text-center text-muted-foreground">
                    {tab === 'trucks' ? t('insurance.empty') : t('documents.emptyDrivers')}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow key={row.id} className={cn('border-border/50', row.dimmed && 'opacity-50')}>
                    <TableCell className="sticky left-0 z-10 bg-card">
                      <button
                        type="button"
                        className="flex flex-col text-left hover:underline"
                        onClick={() => navigate(row.href)}
                      >
                        <span className="whitespace-nowrap font-medium">{row.title}</span>
                        {row.subtitle && <span className="text-xs text-muted-foreground">{row.subtitle}</span>}
                      </button>
                    </TableCell>
                    {columns.map(({ field, labelKey }) => (
                      <TableCell key={field}>
                        <DocumentDateCell
                          value={row.dates[field]}
                          today={today}
                          ariaLabel={t('documents.editAria', { name: row.title, document: t(labelKey) })}
                          onCommit={(value) => commit(row, field, value)}
                        />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </Card>
    </div>
  );
}
