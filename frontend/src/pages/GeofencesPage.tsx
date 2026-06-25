import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNow } from 'date-fns';
import { LogIn, LogOut, MapPin, Plus, Trash2 } from 'lucide-react';

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
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ApiError } from '@/lib/api';
import { geofencesApi, type Geofence } from '@/lib/geofences';
import { useTrucks } from '@/contexts/TruckContext';
import { toast } from '@/hooks/use-toast';

const GEOFENCES_KEY = ['geofences'] as const;
const EVENTS_KEY = ['geofence-events'] as const;

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

interface FormState {
  name: string;
  category: string;
  lat: string;
  lng: string;
  radius: string;
}

const EMPTY_FORM: FormState = { name: '', category: '', lat: '', lng: '', radius: '500' };

export default function GeofencesPage() {
  const { t } = useTranslation();
  const { trucks } = useTrucks();
  const queryClient = useQueryClient();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);

  const { data: geofences = [], isLoading } = useQuery({
    queryKey: GEOFENCES_KEY,
    queryFn: geofencesApi.list,
  });

  const { data: events = [] } = useQuery({
    queryKey: EVENTS_KEY,
    queryFn: () => geofencesApi.events(50),
    refetchInterval: 15_000,
  });

  const truckLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const truck of trucks) out[truck.id] = `${truck.name} (${truck.plateNumber})`;
    return out;
  }, [trucks]);

  const geofenceNames = useMemo(() => {
    const out: Record<string, string> = {};
    for (const g of geofences) out[g.id] = g.name;
    return out;
  }, [geofences]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: GEOFENCES_KEY });
    queryClient.invalidateQueries({ queryKey: EVENTS_KEY });
  };

  const createMutation = useMutation({
    mutationFn: geofencesApi.create,
    onSuccess: () => {
      setDialogOpen(false);
      setForm(EMPTY_FORM);
      invalidate();
    },
    onError: (err) =>
      toast({ title: t('geofences.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => geofencesApi.update(id, { active }),
    onSuccess: invalidate,
    onError: (err) =>
      toast({ title: t('geofences.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const removeMutation = useMutation({
    mutationFn: geofencesApi.remove,
    onSuccess: invalidate,
    onError: (err) =>
      toast({ title: t('geofences.saveFailed'), description: describeError(err, ''), variant: 'destructive' }),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate({
      name: form.name.trim(),
      category: form.category.trim() || undefined,
      centerLat: Number(form.lat),
      centerLng: Number(form.lng),
      radiusM: Number(form.radius),
    });
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('geofences.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('geofences.subtitle')}</p>
        </div>
        <Button onClick={() => setDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('geofences.add')}
        </Button>
      </div>

      {/* Geofences table */}
      <div className="rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('geofences.name')}</TableHead>
              <TableHead>{t('geofences.category')}</TableHead>
              <TableHead>{t('geofences.center')}</TableHead>
              <TableHead>{t('geofences.radius')}</TableHead>
              <TableHead>{t('geofences.status')}</TableHead>
              <TableHead className="w-[1%]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {!isLoading && geofences.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  {t('geofences.noGeofences')}
                </TableCell>
              </TableRow>
            )}
            {geofences.map((g: Geofence) => (
              <TableRow key={g.id}>
                <TableCell className="font-medium">
                  <span className="flex items-center gap-2">
                    <MapPin className="h-4 w-4 text-primary" />
                    {g.name}
                  </span>
                </TableCell>
                <TableCell>{g.category ?? '—'}</TableCell>
                <TableCell className="font-mono text-xs">
                  {g.centerLat.toFixed(5)}, {g.centerLng.toFixed(5)}
                </TableCell>
                <TableCell>{Math.round(g.radiusM)} m</TableCell>
                <TableCell>
                  <Switch
                    checked={g.active}
                    onCheckedChange={(active) => toggleMutation.mutate({ id: g.id, active })}
                  />
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive"
                    onClick={() => {
                      if (window.confirm(t('geofences.confirmDelete'))) removeMutation.mutate(g.id);
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

      {/* Recent events */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">{t('geofences.recentEvents')}</h2>
        <div className="rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('geofences.event')}</TableHead>
                <TableHead>{t('geofences.name')}</TableHead>
                <TableHead>{t('geofences.truck')}</TableHead>
                <TableHead>{t('geofences.time')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                    {t('geofences.noEvents')}
                  </TableCell>
                </TableRow>
              )}
              {events.map((ev) => (
                <TableRow key={ev.id}>
                  <TableCell>
                    <Badge variant={ev.event === 'enter' ? 'default' : 'secondary'}>
                      {ev.event === 'enter' ? (
                        <LogIn className="mr-1 h-3 w-3" />
                      ) : (
                        <LogOut className="mr-1 h-3 w-3" />
                      )}
                      {ev.event === 'enter' ? t('geofences.enter') : t('geofences.exit')}
                    </Badge>
                  </TableCell>
                  <TableCell>{geofenceNames[ev.geofenceId] ?? '—'}</TableCell>
                  <TableCell>{truckLabels[ev.truckId] ?? ev.truckId.slice(0, 8)}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDistanceToNow(ev.recordedAt, { addSuffix: true })}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Create dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('geofences.add')}</DialogTitle>
          </DialogHeader>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="gf-name">{t('geofences.name')}</Label>
              <Input
                id="gf-name"
                required
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="gf-category">{t('geofences.category')}</Label>
              <Input
                id="gf-category"
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                placeholder={t('geofences.categoryPlaceholder')}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="gf-lat">{t('geofences.lat')}</Label>
                <Input
                  id="gf-lat"
                  type="number"
                  step="any"
                  required
                  value={form.lat}
                  onChange={(e) => setForm((f) => ({ ...f, lat: e.target.value }))}
                  placeholder="41.31"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="gf-lng">{t('geofences.lng')}</Label>
                <Input
                  id="gf-lng"
                  type="number"
                  step="any"
                  required
                  value={form.lng}
                  onChange={(e) => setForm((f) => ({ ...f, lng: e.target.value }))}
                  placeholder="69.24"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="gf-radius">{t('geofences.radius')}</Label>
              <Input
                id="gf-radius"
                type="number"
                min={1}
                required
                value={form.radius}
                onChange={(e) => setForm((f) => ({ ...f, radius: e.target.value }))}
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
