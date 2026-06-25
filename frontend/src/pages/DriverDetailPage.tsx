import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  ArrowLeft,
  User,
  Phone,
  Mail,
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
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

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
import { driversApi, type DriverStatus } from '@/lib/drivers';
import { driverDataApi } from '@/lib/driverData';
import { ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';

const statusVariant: Record<DriverStatus, 'default' | 'secondary'> = {
  active: 'default',
  inactive: 'secondary',
  on_leave: 'secondary',
};

const statusLabel: Record<DriverStatus, string> = {
  active: 'Active',
  inactive: 'Inactive',
  on_leave: 'On leave',
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
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [createdCreds, setCreatedCreds] = useState<{ email: string; password: string } | null>(null);

  const generatePassword = () => {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
    let out = '';
    const rnd = new Uint32Array(12);
    crypto.getRandomValues(rnd);
    for (let i = 0; i < 12; i++) out += chars[rnd[i] % chars.length];
    setLoginPassword(out);
  };

  const createLoginMutation = useMutation({
    mutationFn: () => driversApi.createLogin(id, { email: loginEmail.trim(), password: loginPassword }),
    onSuccess: (res) => {
      setCreatedCreds({ email: res.email, password: loginPassword });
      toast({ title: 'App login created' });
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : 'Could not create login';
      toast({ title: 'Failed to create login', description: msg, variant: 'destructive' });
    },
  });

  const openLoginDialog = () => {
    setCreatedCreds(null);
    setLoginEmail(data?.driver.email ?? '');
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
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Drivers
        </Button>
        <p className="text-muted-foreground">Driver not found.</p>
      </div>
    );
  }

  const { driver, currentTruck, latestSafetyScore } = data;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate('/drivers')} title="Back to Drivers">
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">{driver.name}</h1>
            <Badge variant={statusVariant[driver.status]}>{statusLabel[driver.status]}</Badge>
          </div>
          <p className="text-muted-foreground font-mono text-sm">{driver.licenseNumber}</p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Contact */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <User className="h-5 w-5" /> Contact
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-border/50">
            <InfoRow icon={<Phone className="h-4 w-4" />} label="Phone">
              {driver.phone || '—'}
            </InfoRow>
            <InfoRow icon={<Mail className="h-4 w-4" />} label="Email">
              {driver.email || '—'}
            </InfoRow>
          </CardContent>
        </Card>

        {/* License */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <IdCard className="h-5 w-5" /> License
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-border/50">
            <InfoRow icon={<IdCard className="h-4 w-4" />} label="License number">
              <span className="font-mono">{driver.licenseNumber}</span>
            </InfoRow>
            <InfoRow icon={<CalendarClock className="h-4 w-4" />} label="Expires">
              {driver.licenseExpiry
                ? new Date(driver.licenseExpiry).toLocaleDateString()
                : '—'}
            </InfoRow>
          </CardContent>
        </Card>

        {/* Current truck */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <TruckIcon className="h-5 w-5" /> Assigned Truck
            </CardTitle>
          </CardHeader>
          <CardContent>
            {currentTruck ? (
              <InfoRow icon={<TruckIcon className="h-4 w-4" />} label="Truck">
                <Link to={`/trucks/${currentTruck.id}`} className="text-primary hover:underline">
                  {currentTruck.name} ({currentTruck.plateNumber})
                </Link>
              </InfoRow>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Not currently assigned to a truck.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Safety score */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <ShieldCheck className="h-5 w-5" /> Safety Score
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
                  <InfoRow icon={<Gauge className="h-4 w-4" />} label="Speeding events">
                    {latestSafetyScore.speedingEvents}
                  </InfoRow>
                  <InfoRow icon={<Gauge className="h-4 w-4" />} label="Harsh braking">
                    {latestSafetyScore.harshBraking}
                  </InfoRow>
                  <InfoRow icon={<Gauge className="h-4 w-4" />} label="Harsh acceleration">
                    {latestSafetyScore.harshAcceleration}
                  </InfoRow>
                  <InfoRow icon={<Gauge className="h-4 w-4" />} label="Idle time">
                    {latestSafetyScore.idleTimeMinutes} min
                  </InfoRow>
                </div>
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No safety score recorded yet.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Mobile app access */}
        <Card className="border-border/50 bg-card md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Smartphone className="h-5 w-5" /> Mobile App Access
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              Create a login so {driver.name} can sign in to the FleetWatch driver app and
              receive trips, send GPS, and log fuel/expenses.
            </p>
            <Button onClick={openLoginDialog} className="shrink-0">
              <KeyRound className="mr-2 h-4 w-4" /> Create app login
            </Button>
          </CardContent>
        </Card>

        {/* Expenses logged from the app */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Receipt className="h-5 w-5" /> Recent Expenses
            </CardTitle>
          </CardHeader>
          <CardContent>
            {expenses.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No expenses logged from the app.
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
                            <ExternalLink className="h-3 w-3" /> Receipt
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
              <Clock className="h-5 w-5" /> Recent Shifts
            </CardTitle>
          </CardHeader>
          <CardContent>
            {shifts.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No shifts recorded from the app.
              </p>
            ) : (
              <div className="divide-y divide-border/50">
                {shifts.slice(0, 8).map((s) => (
                  <div key={s.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <div>
                      <div className="flex items-center gap-2">
                        <Badge variant={s.status === 'active' ? 'default' : 'secondary'}>
                          {s.status === 'active' ? 'On shift' : 'Ended'}
                        </Badge>
                        {s.truckPlate && (
                          <span className="text-xs text-muted-foreground">{s.truckPlate}</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Started {formatDistanceToNow(new Date(s.startedAt), { addSuffix: true })}
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
            <DialogTitle>Create app login — {driver.name}</DialogTitle>
          </DialogHeader>

          {createdCreds ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Login created. Share these credentials with the driver — the password is shown
                only once.
              </p>
              <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-4 text-sm">
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground">Email</span>
                  <span className="font-mono">{createdCreds.email}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground">Password</span>
                  <span className="font-mono">{createdCreds.password}</span>
                </div>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => {
                    navigator.clipboard?.writeText(
                      `Email: ${createdCreds.email}\nPassword: ${createdCreds.password}`,
                    );
                    toast({ title: 'Copied to clipboard' });
                  }}
                >
                  Copy
                </Button>
                <Button onClick={() => setLoginOpen(false)}>Done</Button>
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
                <Label htmlFor="login-email">Email</Label>
                <Input
                  id="login-email"
                  type="email"
                  required
                  placeholder="driver@example.com"
                  value={loginEmail}
                  onChange={(e) => setLoginEmail(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="login-password">Password</Label>
                <div className="flex gap-2">
                  <Input
                    id="login-password"
                    required
                    minLength={8}
                    placeholder="At least 8 characters"
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                  />
                  <Button type="button" variant="outline" onClick={generatePassword}>
                    Generate
                  </Button>
                </div>
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setLoginOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={createLoginMutation.isPending}>
                  Create login
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
