import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { tripsApi, placesForStage, TRIP_STAGES, type StagePlace, type TripStage } from '@/lib/trips';
import { ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';

interface Props {
  tripId: string;
  /** Called once the checkpoint is saved — the list closes its popover. */
  onSaved?: () => void;
}

/**
 * Report a checkpoint on the driver's behalf: the stage, then where.
 *
 * One component for the trip page and the trips list, so a dispatcher who
 * changes a status from either place writes the same timeline entry.
 */
export function TripStagePicker({ tripId, onSaved }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<TripStage | ''>('');
  const [place, setPlace] = useState<StagePlace | ''>('');

  const mutation = useMutation({
    mutationFn: () => tripsApi.advanceStage(tripId, stage as TripStage, place || null),
    onSuccess: () => {
      setStage('');
      setPlace('');
      queryClient.invalidateQueries({ queryKey: ['trip', tripId] });
      queryClient.invalidateQueries({ queryKey: ['trips'] });
      toast({ title: t('trips.advanced') });
      onSaved?.();
    },
    onError: (err) =>
      toast({
        title: t('trips.saveFailed'),
        description: err instanceof ApiError ? err.detail : err instanceof Error ? err.message : '',
        variant: 'destructive',
      }),
  });

  return (
    <div className="space-y-3">
      <Select
        value={stage}
        onValueChange={(v) => {
          setStage(v as TripStage);
          // A crossing is not a country: the old choice may not apply.
          setPlace('');
        }}
      >
        <SelectTrigger>
          <SelectValue placeholder={t('tripDetail.pickStage')} />
        </SelectTrigger>
        <SelectContent>
          {TRIP_STAGES.map((s) => (
            <SelectItem key={s} value={s}>
              {t(`trips.stage.${s}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {stage && (
        <div className="flex flex-wrap gap-2">
          {placesForStage(stage).map((p) => (
            <Button
              key={p}
              type="button"
              size="sm"
              variant={place === p ? 'default' : 'outline'}
              onClick={() => setPlace(p)}
            >
              {t(`trips.place.${p}`)}
            </Button>
          ))}
        </div>
      )}
      <Button
        className="w-full"
        disabled={!stage || !place || mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {t('tripDetail.saveStage')}
      </Button>
    </div>
  );
}
