import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Plus, Trash2, Plane } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError } from '@/lib/api';
import {
  dmy,
  russiaStaysApi,
  stayLevel,
  type RussiaStay,
  type StayInput,
  type StaySummary,
} from '@/lib/russiaStays';
import { cn } from '@/lib/utils';
import { toast } from '@/hooks/use-toast';

const LEVEL_CLASS = {
  ok: 'border-border/50',
  soon: 'border-status-stopped/60 bg-status-stopped/5',
  urgent: 'border-destructive/60 bg-destructive/5',
  over: 'border-destructive bg-destructive/10',
} as const;

function SummaryLine({ summary }: { summary: StaySummary }) {
  const { t } = useTranslation();
  const level = stayLevel(summary);
  if (!summary.in_russia) {
    return (
      <div className="space-y-1 text-sm">
        <p className="font-medium">{t('russiaStay.notInRussia')}</p>
        <p className="text-muted-foreground">
          {t('russiaStay.used', { n: summary.days_used })} · {t('russiaStay.available', { n: Math.max(0, summary.days_available) })}
        </p>
      </div>
    );
  }
  const left = summary.days_to_leave ?? 0;
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
      <div>
        <p className="text-xs text-muted-foreground">{t('russiaStay.inRussia')}</p>
        <p className="text-2xl font-bold">{t('russiaStay.dayOfStay', { day: summary.day_of_stay })}</p>
      </div>
      <div>
        <p className="text-xs text-muted-foreground">{t('russiaStay.leaveBy')}</p>
        <p className="text-2xl font-bold">{dmy(summary.must_leave_by)}</p>
      </div>
      <Badge variant={level === 'ok' ? 'secondary' : 'destructive'} className="mb-1">
        {level === 'over'
          ? t('russiaStay.overstay', { n: summary.overstay_days || -left })
          : left === 0
            ? t('russiaStay.leaveToday')
            : t('russiaStay.daysLeft', { n: left })}
      </Badge>
      <p className="w-full text-xs text-muted-foreground">{t('russiaStay.used', { n: summary.days_used })}</p>
    </div>
  );
}

interface StayDialogProps {
  stay: RussiaStay | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (input: StayInput) => void;
  pending: boolean;
}

function StayDialog({ stay, open, onOpenChange, onSave, pending }: StayDialogProps) {
  const { t } = useTranslation();
  const [entered, setEntered] = useState(stay?.entered_on ?? '');
  const [left, setLeft] = useState(stay?.left_on ?? '');
  const [note, setNote] = useState(stay?.note ?? '');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{stay ? t('russiaStay.edit') : t('russiaStay.add')}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t('russiaStay.hint')}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="stay-entered">{t('russiaStay.entered')}</Label>
            <Input id="stay-entered" type="date" value={entered} onChange={(e) => setEntered(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="stay-left">{t('russiaStay.left')}</Label>
            <Input id="stay-left" type="date" value={left} onChange={(e) => setLeft(e.target.value)} />
          </div>
        </div>
        <div className="space-y-1">
          <Label htmlFor="stay-note">{t('russiaStay.note')}</Label>
          <Input id="stay-note" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
        </div>
        <DialogFooter>
          <Button
            disabled={!entered || pending}
            onClick={() => onSave({ entered_on: entered, left_on: left || null, note: note.trim() || null })}
          >
            {t('russiaStay.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * One driver's days in Russia: where the 90-in-180 count stands, and every
 * stay behind it — written by the border checkpoint, corrected here by the
 * desk against the migration card.
 */
export function RussiaStayCard({ driverId }: { driverId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ['russia-stays', driverId];
  // `undefined` = closed; `null` = adding a new one.
  const [editing, setEditing] = useState<RussiaStay | null | undefined>(undefined);

  const { data } = useQuery({ queryKey: key, queryFn: () => russiaStaysApi.forDriver(driverId) });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: key });
    queryClient.invalidateQueries({ queryKey: ['russia-stays', 'fleet'] });
  };
  const onError = (err: unknown) =>
    toast({
      title: t('russiaStay.failed'),
      description: err instanceof ApiError ? err.detail : undefined,
      variant: 'destructive',
    });

  const save = useMutation({
    mutationFn: (input: StayInput) =>
      editing ? russiaStaysApi.update(driverId, editing.id, input) : russiaStaysApi.add(driverId, input),
    onSuccess: () => {
      setEditing(undefined);
      refresh();
      toast({ title: t('russiaStay.saved') });
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: (stayId: string) => russiaStaysApi.remove(driverId, stayId),
    onSuccess: refresh,
    onError,
  });

  const level = data ? stayLevel(data.summary) : 'ok';

  return (
    <Card className={cn('bg-card md:col-span-2', LEVEL_CLASS[level])}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-lg">
          <Plane className="h-5 w-5" /> {t('russiaStay.title')}
        </CardTitle>
        <Button size="sm" variant="outline" onClick={() => setEditing(null)}>
          <Plus className="mr-2 h-4 w-4" /> {t('russiaStay.add')}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {data && <SummaryLine summary={data.summary} />}
        {data && data.stays.length === 0 && <p className="text-sm text-muted-foreground">{t('russiaStay.empty')}</p>}
        {data && data.stays.length > 0 && (
          <ul className="divide-y divide-border rounded-md border border-border text-sm">
            {data.stays.map((stay) => (
              <li key={stay.id} className="flex items-center gap-3 px-3 py-2">
                <span className="font-medium">
                  {dmy(stay.entered_on)} → {stay.left_on ? dmy(stay.left_on) : t('russiaStay.stillInside')}
                </span>
                <Badge variant="outline" className="text-xs">
                  {t(`russiaStay.source.${stay.source}`, { defaultValue: stay.source })}
                </Badge>
                {stay.note && <span className="truncate text-muted-foreground">{stay.note}</span>}
                <span className="ml-auto flex gap-1">
                  <Button variant="ghost" size="icon" title={t('russiaStay.edit')} onClick={() => setEditing(stay)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive"
                    title={t('russiaStay.delete')}
                    onClick={() => window.confirm(t('russiaStay.confirmDelete')) && remove.mutate(stay.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      {editing !== undefined && (
        <StayDialog
          key={editing?.id ?? 'new'}
          stay={editing}
          open
          onOpenChange={(open) => !open && setEditing(undefined)}
          onSave={(input) => save.mutate(input)}
          pending={save.isPending}
        />
      )}
    </Card>
  );
}
