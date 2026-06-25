import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNow } from 'date-fns';
import { Copy, KeyRound, Plus, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { devicesApi, type Device } from '@/lib/devices';
import { ApiError } from '@/lib/api';
import { useTrucks } from '@/contexts/TruckContext';
import { toast } from '@/hooks/use-toast';

const DEVICES_KEY = ['devices'] as const;
const ONLINE_THRESHOLD_MS = 60_000;

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

function isOnline(device: Device): boolean {
  if (!device.lastSeenAt) return false;
  return Date.now() - device.lastSeenAt.getTime() < ONLINE_THRESHOLD_MS;
}

export default function DevicesPage() {
  const { t } = useTranslation();
  const { trucks } = useTrucks();
  const queryClient = useQueryClient();

  const [enrollOpen, setEnrollOpen] = useState(false);
  const [imei, setImei] = useState('');
  const [name, setName] = useState('');
  const [truckId, setTruckId] = useState<string>('');
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  const { data: devices = [], isLoading } = useQuery({
    queryKey: DEVICES_KEY,
    queryFn: devicesApi.list,
    refetchInterval: 30_000,
  });

  const truckLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const truck of trucks) out[truck.id] = `${truck.name} (${truck.plateNumber})`;
    return out;
  }, [trucks]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: DEVICES_KEY });

  const enrollMutation = useMutation({
    mutationFn: devicesApi.enroll,
    onSuccess: (device) => {
      setRevealedKey(device.apiKey);
      setEnrollOpen(false);
      setImei('');
      setName('');
      setTruckId('');
      invalidate();
      toast({ title: t('devices.enrollSuccess') });
    },
    onError: (err) => {
      toast({
        title: t('devices.saveFailed'),
        description: describeError(err, ''),
        variant: 'destructive',
      });
    },
  });

  const rotateMutation = useMutation({
    mutationFn: devicesApi.rotateKey,
    onSuccess: ({ apiKey }) => {
      setRevealedKey(apiKey);
    },
    onError: (err) => {
      toast({
        title: t('devices.saveFailed'),
        description: describeError(err, ''),
        variant: 'destructive',
      });
    },
  });

  const removeMutation = useMutation({
    mutationFn: devicesApi.remove,
    onSuccess: () => invalidate(),
    onError: (err) => {
      toast({
        title: t('devices.saveFailed'),
        description: describeError(err, ''),
        variant: 'destructive',
      });
    },
  });

  const copyKey = async () => {
    if (!revealedKey) return;
    try {
      await navigator.clipboard.writeText(revealedKey);
      toast({ title: t('devices.apiKeyCopied') });
    } catch {
      /* clipboard might be blocked; user can select+copy manually */
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">{t('devices.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('devices.subtitle')}</p>
        </div>
        <Button onClick={() => setEnrollOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('devices.enroll')}
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('devices.imei')}</TableHead>
              <TableHead>{t('devices.name')}</TableHead>
              <TableHead>{t('devices.truck')}</TableHead>
              <TableHead>{t('devices.status')}</TableHead>
              <TableHead>{t('devices.lastSeen')}</TableHead>
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
            {!isLoading && devices.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  {t('devices.noDevices')}
                </TableCell>
              </TableRow>
            )}
            {devices.map((device) => {
              const online = isOnline(device);
              return (
                <TableRow key={device.id}>
                  <TableCell className="font-mono text-xs">{device.imei}</TableCell>
                  <TableCell>{device.name ?? '—'}</TableCell>
                  <TableCell>
                    {device.truckId
                      ? (truckLabels[device.truckId] ?? device.truckId)
                      : (
                        <span className="text-muted-foreground italic">
                          {t('devices.unassigned')}
                        </span>
                      )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={online ? 'default' : 'secondary'}>
                      <span
                        className={`mr-1.5 inline-block h-2 w-2 rounded-full ${
                          online ? 'bg-green-500' : 'bg-muted-foreground'
                        }`}
                      />
                      {online ? t('devices.online') : t('devices.offline')}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {device.lastSeenAt
                      ? formatDistanceToNow(device.lastSeenAt, { addSuffix: true })
                      : t('devices.never')}
                  </TableCell>
                  <TableCell className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => {
                        if (window.confirm(t('devices.confirmRotate'))) {
                          rotateMutation.mutate(device.id);
                        }
                      }}
                      title={t('devices.rotateKey')}
                    >
                      <KeyRound className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-destructive hover:text-destructive"
                      onClick={() => {
                        if (window.confirm(t('devices.confirmDelete'))) {
                          removeMutation.mutate(device.id);
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Enroll dialog */}
      <Dialog open={enrollOpen} onOpenChange={setEnrollOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('devices.enroll')}</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              enrollMutation.mutate({
                imei: imei.trim(),
                name: name.trim() || undefined,
                truckId: truckId || undefined,
              });
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="imei">{t('devices.imei')}</Label>
              <Input
                id="imei"
                required
                minLength={8}
                maxLength={32}
                value={imei}
                onChange={(e) => setImei(e.target.value)}
                placeholder="352094081234567"
                className="font-mono"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="device-name">{t('devices.name')}</Label>
              <Input
                id="device-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Teltonika FMB920 — Truck Alpha"
              />
            </div>
            <div className="space-y-2">
              <Label>{t('devices.truck')}</Label>
              <Select value={truckId} onValueChange={setTruckId}>
                <SelectTrigger>
                  <SelectValue placeholder={t('devices.unassigned')} />
                </SelectTrigger>
                <SelectContent>
                  {trucks.map((truck) => (
                    <SelectItem key={truck.id} value={truck.id}>
                      {truck.name} ({truck.plateNumber})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEnrollOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={enrollMutation.isPending}>
                {t('devices.enroll')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* One-time API key reveal */}
      <Dialog open={revealedKey !== null} onOpenChange={(open) => !open && setRevealedKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API key</DialogTitle>
            <DialogDescription className="text-destructive">
              {t('devices.apiKeyWarning')}
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 rounded-md border border-border bg-muted p-3">
            <code className="flex-1 break-all text-sm font-mono">{revealedKey}</code>
            <Button variant="ghost" size="icon" onClick={copyKey} title="Copy">
              <Copy className="h-4 w-4" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setRevealedKey(null)}>{t('common.save')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
