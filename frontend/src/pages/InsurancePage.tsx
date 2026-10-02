/**
 * Every rig's insurance on one screen: a policy per country (UZ, KZ, RU),
 * each with its own expiry, editable in place.
 *
 * The dates already drive the reminders — the driver's phone and the owner's
 * Telegram are warned a month out, a week out and on the day — but a reminder
 * says one thing about one truck. This is where the dispatcher sees the whole
 * fleet's cover at once and types in the new date when a policy is renewed.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ShieldAlert, ShieldCheck, ShieldQuestion, Search } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
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
import { useTrucks } from '@/contexts/TruckContext';
import {
  INSURANCE_POLICIES,
  daysLeft,
  insuranceState,
  localToday,
  nearestDaysLeft,
  summarize,
  type InsuranceField,
  type InsuranceState,
} from '@/lib/insurance';
import { cn } from '@/lib/utils';
import type { Truck } from '@/types';

type SortMode = 'list' | 'urgent';
type FilterMode = 'all' | 'attention';

const STATE_CLASSES: Record<InsuranceState, string> = {
  expired: 'bg-destructive/15 text-destructive border-destructive/30',
  urgent: 'bg-status-stopped/20 text-status-stopped border-status-stopped/30',
  soon: 'bg-yellow-500/15 text-yellow-600 dark:text-yellow-400 border-yellow-500/30',
  ok: 'bg-status-moving/15 text-status-moving border-status-moving/30',
  missing: 'bg-muted text-muted-foreground border-border',
};

function PolicyCell({
  truck,
  field,
  country,
  today,
}: {
  truck: Truck;
  field: InsuranceField;
  country: string;
  today: string;
}) {
  const { t } = useTranslation();
  const { updateTruck } = useTrucks();
  const saved = truck[field] ?? '';
  // Held locally and saved on blur: typing a date into the segments fires a
  // change per complete date, and a save per keystroke is a toast per keystroke.
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);

  const state = insuranceState(draft, today);
  const days = draft ? daysLeft(draft, today) : 0;
  const label =
    state === 'missing'
      ? t('insurance.state.missing')
      : state === 'expired'
        ? t('insurance.state.expired', { count: Math.abs(days) })
        : t('insurance.state.left', { count: days });

  const commit = () => {
    if (draft !== saved) updateTruck(truck.id, { [field]: draft || null });
  };

  return (
    <div className="flex min-w-[9.5rem] flex-col gap-1">
      <Input
        type="date"
        value={draft}
        className="h-8 bg-secondary/50 border-0 px-2 text-sm"
        aria-label={t('insurance.editAria', { plate: truck.plateNumber, country: t(`insurance.country.${country}`) })}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
        }}
      />
      <Badge variant="outline" className={cn('w-fit text-[11px] font-normal', STATE_CLASSES[state])}>
        {label}
      </Badge>
    </div>
  );
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

export default function InsurancePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { trucks, isLoading } = useTrucks();
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortMode>('list');
  const [filter, setFilter] = useState<FilterMode>('all');
  const today = localToday();

  const summary = useMemo(() => summarize(trucks, today), [trucks, today]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = trucks.filter(
      (truck) => !q || truck.plateNumber.toLowerCase().includes(q) || truck.name.toLowerCase().includes(q),
    );
    if (filter === 'attention') {
      list = list.filter((truck) =>
        INSURANCE_POLICIES.some(({ field }) => {
          const state = insuranceState(truck[field], today);
          return state === 'expired' || state === 'urgent' || state === 'soon';
        }),
      );
    }
    if (sort === 'urgent') {
      // Trucks with no date at all go last: there is nothing to renew yet,
      // only something to fill in.
      list = [...list].sort(
        (a, b) => (nearestDaysLeft(a, today) ?? Infinity) - (nearestDaysLeft(b, today) ?? Infinity),
      );
    }
    return list;
  }, [trucks, search, filter, sort, today]);

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('insurance.title')}</h1>
        <p className="text-muted-foreground">{t('insurance.subtitle')}</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <SummaryCard
          icon={ShieldAlert}
          value={summary.expired}
          label={t('insurance.summary.expired')}
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
              placeholder={t('insurance.searchPlaceholder')}
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
              <SelectItem value="all">{t('insurance.filter.all')}</SelectItem>
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
                <TableHead className="text-muted-foreground">{t('trucks.colTruck')}</TableHead>
                {INSURANCE_POLICIES.map(({ country }) => (
                  <TableHead key={country} className="text-muted-foreground">
                    {t(`insurance.country.${country}`)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-12 text-center text-muted-foreground">
                    {t('common.loading')}
                  </TableCell>
                </TableRow>
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-12 text-center text-muted-foreground">
                    {t('insurance.empty')}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((truck) => (
                  <TableRow key={truck.id} className={cn('border-border/50', !truck.isEnabled && 'opacity-50')}>
                    <TableCell>
                      <button
                        type="button"
                        className="flex flex-col text-left hover:underline"
                        onClick={() => navigate(`/trucks/${truck.id}`)}
                      >
                        <span className="font-medium">{truck.plateNumber}</span>
                        {truck.name !== truck.plateNumber && (
                          <span className="text-xs text-muted-foreground">{truck.name}</span>
                        )}
                      </button>
                    </TableCell>
                    {INSURANCE_POLICIES.map(({ field, country }) => (
                      <TableCell key={field}>
                        <PolicyCell truck={truck} field={field} country={country} today={today} />
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
