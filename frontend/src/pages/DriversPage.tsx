import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, Link as LinkIcon, Unlink } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
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
import { driversApi, type Driver, type DriverStatus } from '@/lib/drivers';
import { ApiError } from '@/lib/api';
import { useTrucks } from '@/contexts/TruckContext';
import { toast } from '@/hooks/use-toast';

const DRIVERS_KEY = ['drivers'] as const;

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function DriversPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { trucks } = useTrucks();
  const queryClient = useQueryClient();

  const [createOpen, setCreateOpen] = useState(false);
  const [assignTarget, setAssignTarget] = useState<Driver | null>(null);
  const [form, setForm] = useState({
    name: '',
    phone: '',
    email: '',
    licenseNumber: '',
    licenseExpiry: '',
    status: 'active' as DriverStatus,
  });
  const [assignTruckId, setAssignTruckId] = useState<string>('');

  const { data: drivers = [], isLoading } = useQuery({
    queryKey: DRIVERS_KEY,
    queryFn: driversApi.list,
    refetchInterval: 60_000,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: DRIVERS_KEY });

  const createMutation = useMutation({
    mutationFn: driversApi.create,
    onSuccess: () => {
      setCreateOpen(false);
      setForm({
        name: '',
        phone: '',
        email: '',
        licenseNumber: '',
        licenseExpiry: '',
        status: 'active',
      });
      invalidate();
      toast({ title: t('drivers.created') });
    },
    onError: (err) =>
      toast({
        title: t('drivers.saveFailed'),
        description: describeError(err, ''),
        variant: 'destructive',
      }),
  });

  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: DriverStatus }) =>
      driversApi.update(id, { status }),
    onSuccess: () => {
      invalidate();
      toast({ title: t('drivers.updated') });
    },
    onError: (err) =>
      toast({ title: t('drivers.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const assignMutation = useMutation({
    mutationFn: ({ driverId, truckId }: { driverId: string; truckId: string }) =>
      driversApi.assign(driverId, truckId),
    onSuccess: () => {
      setAssignTarget(null);
      setAssignTruckId('');
      invalidate();
      toast({ title: t('drivers.assigned') });
    },
    onError: (err) =>
      toast({ title: t('drivers.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const unassignMutation = useMutation({
    mutationFn: driversApi.unassign,
    onSuccess: () => invalidate(),
    onError: (err) =>
      toast({ title: t('drivers.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const removeMutation = useMutation({
    mutationFn: driversApi.remove,
    onSuccess: () => {
      invalidate();
      toast({ title: t('drivers.deleted') });
    },
    onError: (err) =>
      toast({ title: t('drivers.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const statusLabel: Record<DriverStatus, string> = {
    active: t('drivers.statusActive'),
    inactive: t('drivers.statusInactive'),
    on_leave: t('drivers.statusOnLeave'),
  };

  // For the assigned-truck cell we need a driver→truck map. The backend
  // current_truck lives on the detail endpoint; to avoid N+1 here, we leave
  // the cell empty until we fetch that relationship. (A cheap follow-up:
  // add a GET /api/drivers?expand=current_truck to the backend.)
  const trucksById = useMemo(() => {
    const out: Record<string, string> = {};
    for (const tr of trucks) out[tr.id] = `${tr.name} (${tr.plateNumber})`;
    return out;
  }, [trucks]);

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('drivers.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('drivers.subtitle')}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('drivers.add')}
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('drivers.name')}</TableHead>
              <TableHead>{t('drivers.license')}</TableHead>
              <TableHead>{t('drivers.phone')}</TableHead>
              <TableHead>{t('drivers.status')}</TableHead>
              <TableHead className="w-[1%]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {!isLoading && drivers.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  {t('drivers.noDrivers')}
                </TableCell>
              </TableRow>
            )}
            {drivers.map((d) => (
              <TableRow
                key={d.id}
                className="cursor-pointer"
                onClick={() => navigate(`/drivers/${d.id}`)}
              >
                <TableCell className="font-medium">{d.name}</TableCell>
                <TableCell className="font-mono text-xs">{d.licenseNumber}</TableCell>
                <TableCell>{d.phone ?? '—'}</TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <Select
                    value={d.status}
                    onValueChange={(v) =>
                      updateStatusMutation.mutate({ id: d.id, status: v as DriverStatus })
                    }
                  >
                    <SelectTrigger className="h-8 w-[130px]">
                      <SelectValue>
                        <Badge variant={d.status === 'active' ? 'default' : 'secondary'}>
                          {statusLabel[d.status]}
                        </Badge>
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="active">{t('drivers.statusActive')}</SelectItem>
                      <SelectItem value="inactive">{t('drivers.statusInactive')}</SelectItem>
                      <SelectItem value="on_leave">{t('drivers.statusOnLeave')}</SelectItem>
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      setAssignTarget(d);
                      setAssignTruckId('');
                    }}
                    title={t('drivers.assign')}
                  >
                    <LinkIcon className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => unassignMutation.mutate(d.id)}
                    title={t('drivers.unassignAction')}
                  >
                    <Unlink className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive"
                    onClick={() => {
                      if (window.confirm(t('drivers.confirmDelete'))) {
                        removeMutation.mutate(d.id);
                      }
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

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('drivers.add')}</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate({
                name: form.name.trim(),
                licenseNumber: form.licenseNumber.trim(),
                phone: form.phone.trim() || undefined,
                email: form.email.trim() || undefined,
                licenseExpiry: form.licenseExpiry || undefined,
                status: form.status,
              });
            }}
            className="space-y-3"
          >
            <div className="space-y-2">
              <Label htmlFor="d-name">{t('drivers.name')}</Label>
              <Input
                id="d-name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="d-license">{t('drivers.license')}</Label>
              <Input
                id="d-license"
                required
                value={form.licenseNumber}
                onChange={(e) => setForm({ ...form, licenseNumber: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="d-phone">{t('drivers.phone')}</Label>
                <Input
                  id="d-phone"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="d-email">{t('drivers.email')}</Label>
                <Input
                  id="d-email"
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="d-expiry">{t('drivers.licenseExpiry')}</Label>
              <Input
                id="d-expiry"
                type="date"
                value={form.licenseExpiry}
                onChange={(e) => setForm({ ...form, licenseExpiry: e.target.value })}
              />
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
        </DialogContent>
      </Dialog>

      {/* Assign dialog */}
      <Dialog open={assignTarget !== null} onOpenChange={(open) => !open && setAssignTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t('drivers.assign')}: {assignTarget?.name}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label>{t('drivers.assignedTruck')}</Label>
            <Select value={assignTruckId} onValueChange={setAssignTruckId}>
              <SelectTrigger>
                <SelectValue placeholder="—" />
              </SelectTrigger>
              <SelectContent>
                {trucks.map((tr) => (
                  <SelectItem key={tr.id} value={tr.id}>
                    {trucksById[tr.id]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              disabled={!assignTruckId || assignMutation.isPending}
              onClick={() => {
                if (assignTarget && assignTruckId) {
                  assignMutation.mutate({ driverId: assignTarget.id, truckId: assignTruckId });
                }
              }}
            >
              {t('drivers.assign')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
