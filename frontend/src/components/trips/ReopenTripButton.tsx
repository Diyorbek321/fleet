import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Undo2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api';
import { tripsApi } from '@/lib/trips';
import { toast } from '@/hooks/use-toast';

/**
 * Undo a "delivered" a driver pressed by mistake. Shown only on a delivered
 * trip; behind a confirmation because it puts the load back on the driver's
 * phone as the current trip.
 */
export function ReopenTripButton({ tripId }: { tripId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');

  const mutation = useMutation({
    mutationFn: () => tripsApi.reopen(tripId, note.trim()),
    onSuccess: () => {
      setOpen(false);
      setNote('');
      queryClient.invalidateQueries({ queryKey: ['trip', tripId] });
      queryClient.invalidateQueries({ queryKey: ['trips'] });
      toast({ title: t('tripDetail.reopen.done') });
    },
    onError: (err) =>
      toast({
        title: t('trips.saveFailed'),
        description: err instanceof ApiError ? err.detail : String(err),
        variant: 'destructive',
      }),
  });

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Undo2 className="mr-2 h-4 w-4" />
        {t('tripDetail.reopen.button')}
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('tripDetail.reopen.title')}</AlertDialogTitle>
            <AlertDialogDescription>{t('tripDetail.reopen.description')}</AlertDialogDescription>
          </AlertDialogHeader>
          <Textarea
            rows={2}
            maxLength={500}
            value={note}
            placeholder={t('tripDetail.reopen.notePlaceholder')}
            onChange={(e) => setNote(e.target.value)}
          />
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              disabled={mutation.isPending}
              onClick={(e) => {
                // Stay open until the server answers, so a failure is seen.
                e.preventDefault();
                mutation.mutate();
              }}
            >
              {t('tripDetail.reopen.confirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
