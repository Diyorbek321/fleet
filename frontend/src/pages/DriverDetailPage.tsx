import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  User,
  Phone,
  Mail,
  ShieldAlert,
  IdCard,
  CalendarClock,
  Truck as TruckIcon,
  ShieldCheck,
  Gauge,
  Smartphone,
  KeyRound,
  Receipt,
  Clock,
  ExternalLink,
  Pencil,
} from 'lucide-react';
import { formatDistanceToNow } from '@/lib/datetime';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { driversApi, type DriverInput, type DriverStatus } from '@/lib/drivers';
import { DriverFormDialog } from '@/components/drivers/DriverFormDialog';
import { DriverMessagesCard } from '@/components/drivers/DriverMessagesCard';
import { driverDataApi } from '@/lib/driverData';
import { ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';

const statusVariant: Record<DriverStatus, 'default' | 'secondary'> = {
  active: 'default',
  inactive: 'secondary',
  on_leave: 'secondary',
};

const statusLabelKey: Record<DriverStatus, string> = {
  active: 'drivers.statusActive',
  inactive: 'drivers.statusInactive',
  on_leave: 'drivers.statusOnLeave',
};

interface InfoRowProps {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}

function InfoRow({ icon, label, children }: InfoRowProps) {
  return (
    <div className="flex items-start gap-3 py-2">
      <span className="mt-0.5 text-muted-foreground">{icon}</span>
      <div className="flex-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="text-sm font-medium">{children}</div>
      </div>
    </div>
  );
}

function scoreColor(score: number): string {
  if (score >= 80) return 'text-status-moving';
  if (score >= 60) return 'text-status-stopped';
  return 'text-destructive';
}

export default function DriverDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['driver', id],
    queryFn: () => driversApi.get(id),
    enabled: Boolean(id),
  });

  // Data the driver submitted from the mobile app.
  const { data: expenses = [] } = useQuery({
    queryKey: ['driver-expenses', id],
    queryFn: () => driverDataApi.expenses(id),
    enabled: Boolean(id),
  });
  const { data: shifts = [] } = useQuery({
    queryKey: ['driver-shifts', id],
    queryFn: () => driverDataApi.shifts(id),
    enabled: Boolean(id),
  });

  // ---- Mobile app login provisioning ----
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const editMutation = useMutation({
    mutationFn: (input: DriverInput) => driversApi.update(id, input),
    onSuccess: () => {
      setEditOpen(false);
      queryClient.invalidateQueries({ queryKey: ['driver', id] });
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

  const [loginOpen, setLoginOpen] = useState(false);
  const [loginValue, setLoginValue] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [createdCreds, setCreatedCreds] = useState<{ login: string; password: string } | null>(null);

  const { data: currentLogin = null } = useQuery({
    queryKey: ['driver-login', id],
    queryFn: () => driversApi.getLogin(id),
    enabled: Boolean(id),
  });

  const generatePassword = () => {
    // Lower-case and digits only: the driver types this on a phone, where a
    // capital letter is the keyboard's guess, not the driver's.
    const chars = 'abcdefghijkmnpqrstuvwxyz23456789';
    let out = '';
    const rnd = new Uint32Array(10);
    crypto.getRandomValues(rnd);
    for (let i = 0; i < 10; i++) out += chars[rnd[i] % chars.length];
    setLoginPassword(out);
  };

  const createLoginMutation = useMutation({
    mutationFn: () => driversApi.createLogin(id, { login: loginValue.trim(), password: loginPassword }),
    onSuccess: (res) => {
      setCreatedCreds({ login: res.login, password: loginPassword });
      queryClient.invalidateQueries({ queryKey: ['driver-login', id] });
      toast({ title: t('drivers.detail.toastCreated') });
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : t('drivers.detail.createFailed');
      toast({ title: t('drivers.detail.toastFailed'), description: msg, variant: 'destructive' });
    },
  });

  const openLoginDialog = () => {
    setCreatedCreds(null);
    setLoginValue(currentLogin ?? '');
    setLoginPassword('');
    setLoginOpen(true);
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-40" />
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" onClick={() => navigate('/drivers')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('drivers.detail.back')}
        </Button>
        <p className="text-muted-foreground">{t('drivers.detail.notFound')}</p>
      </div>
    );
  }

  const { driver, currentTruck, latestSafetyScore } = data;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate('/drivers')} title={t('drivers.detail.back')}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">{driver.name}</h1>
            <Badge variant={statusVariant[driver.status]}>{t(statusLabelKey[driver.status])}</Badge>
          </div>
          <p className="text-muted-foreground font-mono text-sm">
            {driver.passportNumber ?? driver.licenseNumber ?? ''}
          </p>
        </div>
        <Button variant="outline" size="sm" className="ml-auto" onClick={() => setEditOpen(true)}>
          <Pencil className="mr-2 h-4 w-4" /> {t('common.edit')}
        </Button>
      </div>

      <DriverFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        driver={driver}
        isPending={editMutation.isPending}
        onSubmit={(input) => editMutation.mutate(input)}
      />

      <div className="grid gap-6 md:grid-cols-2">
        {/* Contact */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <User className="h-5 w-5" /> {t('drivers.detail.contact')}
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-border/50">
            <InfoRow icon={<Phone className="h-4 w-4" />} label={t('drivers.phoneUz')}>
              {driver.phone || '—'}
            </InfoRow>
            {/* Only the numbers that exist: a row of dashes for the two SIMs a
                driver does not have reads as missing data, not as absent. */}
            {driver.phone2 && (
              <InfoRow icon={<Phone className="h-4 w-4" />} label={t('drivers.phoneKz')}>
                {driver.phone2}
              </InfoRow>
            )}
            {driver.phone3 && (
              <InfoRow icon={<Phone className="h-4 w-4" />} label={t('drivers.phoneRu')}>
                {driver.phone3}
              </InfoRow>
            )}
            <InfoRow icon={<ShieldAlert className="h-4 w-4" />} label={t('drivers.adr')}>
              {driver.adr ? t('common.yes') : t('common.no')}
            </InfoRow>
            {/* Kept for drivers entered before the form stopped asking. */}
            {driver.email && (
              <InfoRow icon={<Mail className="h-4 w-4" />} label={t('drivers.email')}>
                {driver.email}
              </InfoRow>
            )}
          </CardContent>
        </Card>

        {/* License */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <IdCard className="h-5 w-5" /> {t('drivers.detail.licenseCard')}
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-border/50">
            <InfoRow icon={<IdCard className="h-4 w-4" />} label={t('drivers.passport')}>
              <span className="font-mono">{driver.passportNumber || '—'}</span>
            </InfoRow>
            {/* The licence is no longer asked for; shown only where one was
                entered before the passport replaced it. */}
            {driver.licenseNumber && (
              <InfoRow icon={<IdCard className="h-4 w-4" />} label={t('drivers.license')}>
                <span className="font-mono">{driver.licenseNumber}</span>
              </InfoRow>
            )}
            {driver.licenseExpiry && (
              <InfoRow icon={<CalendarClock className="h-4 w-4" />} label={t('drivers.detail.expires')}>
                {new Date(driver.licenseExpiry).toLocaleDateString()}
              </InfoRow>
            )}
          </CardContent>
        </Card>

        {/* Current truck */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <TruckIcon className="h-5 w-5" /> {t('drivers.detail.assignedTruck')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {currentTruck ? (
              <InfoRow icon={<TruckIcon className="h-4 w-4" />} label={t('drivers.detail.truck')}>
                <Link to={`/trucks/${currentTruck.id}`} className="text-primary hover:underline">
                  {currentTruck.name} ({currentTruck.plateNumber})
                </Link>
              </InfoRow>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t('drivers.detail.notAssigned')}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Safety score */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <ShieldCheck className="h-5 w-5" /> {t('drivers.detail.safetyScore')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {latestSafetyScore ? (
              <div>
                <div className="mb-3 flex items-baseline gap-2">
                  <span className={`text-4xl font-bold ${scoreColor(latestSafetyScore.score)}`}>
                    {latestSafetyScore.score}
                  </span>
                  <span className="text-sm text-muted-foreground">/ 100</span>
                </div>
                <div className="grid grid-cols-2 gap-x-6 text-sm">
                  <InfoRow icon={<Gauge className="h-4 w-4" />} label={t('drivers.detail.speedingEvents')}>
                    {latestSafetyScore.speedingEvents}
                  </InfoRow>
                  <InfoRow icon={<Gauge className="h-4 w-4" />} label={t('drivers.detail.harshBraking')}>
                    {latestSafetyScore.harshBraking}
                  </InfoRow>
                  <InfoRow icon={<Gauge className="h-4 w-4" />} label={t('drivers.detail.harshAcceleration')}>
                    {latestSafetyScore.harshAcceleration}
                  </InfoRow>
                  <InfoRow icon={<Gauge className="h-4 w-4" />} label={t('drivers.detail.idleTime')}>
                    {latestSafetyScore.idleTimeMinutes} {t('common.minutes')}
                  </InfoRow>
                </div>
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t('drivers.detail.noScore')}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Mobile app access */}
        <Card className="border-border/50 bg-card md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Smartphone className="h-5 w-5" /> {t('drivers.detail.appAccess')}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1 text-sm">
              {currentLogin ? (
                <p>
                  <span className="text-muted-foreground">{t('drivers.detail.login')}: </span>
                  <span className="font-mono font-medium">{currentLogin}</span>
                </p>
              ) : (
                <p className="text-muted-foreground">
                  {t('drivers.detail.appAccessHint', { name: driver.name })}
                </p>
              )}
            </div>
            <Button onClick={openLoginDialog} className="shrink-0">
              <KeyRound className="mr-2 h-4 w-4" />{' '}
              {currentLogin ? t('drivers.detail.resetLogin') : t('drivers.detail.createLogin')}
            </Button>
          </CardContent>
        </Card>

        {/* Messages to the phone: the dispatcher's, and the GPS watcher's. */}
        <DriverMessagesCard driverId={driver.id} />

        {/* Expenses logged from the app */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Receipt className="h-5 w-5" /> {t('drivers.detail.recentExpenses')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {expenses.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t('drivers.detail.noExpenses')}
              </p>
            ) : (
              <div className="divide-y divide-border/50">
                {expenses.slice(0, 8).map((e) => (
                  <div key={e.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium capitalize">{e.category}</span>
                        {e.receiptUrl && (
                          <a
                            href={e.receiptUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1 text-xs text-primary hover:underline"
                          >
                            <ExternalLink className="h-3 w-3" /> {t('drivers.detail.receipt')}
                          </a>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {new Date(e.spentAt).toLocaleDateString()}
                        {e.note ? ` · ${e.note}` : ''}
                        {e.truckPlate ? ` · ${e.truckPlate}` : ''}
                      </p>
                    </div>
                    <span className="font-mono font-medium">{e.amount.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Shifts logged from the app */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Clock className="h-5 w-5" /> {t('drivers.detail.recentShifts')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {shifts.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t('drivers.detail.noShifts')}
              </p>
            ) : (
              <div className="divide-y divide-border/50">
                {shifts.slice(0, 8).map((s) => (
                  <div key={s.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <div>
                      <div className="flex items-center gap-2">
                        <Badge variant={s.status === 'active' ? 'default' : 'secondary'}>
                          {s.status === 'active' ? t('drivers.detail.onShift') : t('drivers.detail.shiftEnded')}
                        </Badge>
                        {s.truckPlate && (
                          <span className="text-xs text-muted-foreground">{s.truckPlate}</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {t('drivers.detail.startedAgo', {
                          ago: formatDistanceToNow(new Date(s.startedAt), { addSuffix: true }),
                        })}
                      </p>
                    </div>
                    {s.startMileage != null && (
                      <span className="font-mono text-xs text-muted-foreground">
                        {s.startMileage.toLocaleString()}
                        {s.endMileage != null ? ` → ${s.endMileage.toLocaleString()} km` : ' km'}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Create-login dialog */}
      <Dialog open={loginOpen} onOpenChange={setLoginOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('drivers.detail.dialogTitle', { name: driver.name })}</DialogTitle>
          </DialogHeader>

          {createdCreds ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t('drivers.detail.createdHint')}
              </p>
              <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-4 text-sm">
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground">{t('drivers.detail.login')}</span>
                  <span className="font-mono">{createdCreds.login}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground">{t('drivers.detail.password')}</span>
                  <span className="font-mono">{createdCreds.password}</span>
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => {
                    navigator.clipboard?.writeText(
                      `Login: ${createdCreds.login}\nParol: ${createdCreds.password}`,
                    );
                    toast({ title: t('common.copied') });
                  }}
                >
                  {t('common.copy')}
                </Button>
                <Button onClick={() => setLoginOpen(false)}>{t('common.done')}</Button>
              </DialogFooter>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                createLoginMutation.mutate();
              }}
              className="space-y-3"
            >
              <div className="space-y-2">
                <Label htmlFor="login-value">{t('drivers.detail.login')}</Label>
                <Input
                  id="login-value"
                  required
                  autoCapitalize="none"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="10422tca"
                  value={loginValue}
                  onChange={(e) => setLoginValue(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">{t('drivers.detail.loginHint')}</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="login-password">{t('drivers.detail.password')}</Label>
                <div className="flex gap-2">
                  <Input
                    id="login-password"
                    required
                    minLength={8}
                    placeholder={t('drivers.detail.passwordPlaceholder')}
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                  />
                  <Button type="button" variant="outline" onClick={generatePassword}>
                    {t('common.generate')}
                  </Button>
                </div>
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setLoginOpen(false)}>
                  {t('common.cancel')}
                </Button>
                <Button type="submit" disabled={createLoginMutation.isPending}>
                  {currentLogin ? t('drivers.detail.resetAction') : t('drivers.detail.createAction')}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
