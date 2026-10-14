import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Check } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { ApiError } from '@/lib/api';
import { updateTripDocument, type TripDocument } from '@/lib/trips';
import { toast } from '@/hooks/use-toast';

/** The categories the driver app offers; a document may carry an older free-text one. */
export const DOCUMENT_CATEGORIES = ['cmr', 'invoice', 'customs', 'other'] as const;

interface DocumentLabelFormProps {
  doc: TripDocument;
  onSaved: (doc: TripDocument) => void;
}

/** Relabel a driver's document photo: its category and a note. */
export function DocumentLabelForm({ doc, onSaved }: DocumentLabelFormProps) {
  const { t } = useTranslation();
  const [category, setCategory] = useState(doc.category ?? '');
  const [caption, setCaption] = useState(doc.caption ?? '');

  const save = useMutation({
    mutationFn: () =>
      updateTripDocument(doc.tripId, doc.id, {
        category: category || null,
        caption: caption.trim() || null,
      }),
    onSuccess: (saved) => {
      onSaved(saved);
      toast({ title: t('tripDetail.docSaved') });
    },
    onError: (err) =>
      toast({
        title: t('trips.saveFailed'),
        description: err instanceof ApiError ? err.detail : undefined,
        variant: 'destructive',
      }),
  });

  const dirty = category !== (doc.category ?? '') || caption.trim() !== (doc.caption ?? '');

  return (
    <div className="space-y-3">
      <ToggleGroup
        type="single"
        variant="outline"
        value={category}
        onValueChange={(v) => v && setCategory(v)}
        className="flex-wrap justify-start"
      >
        {DOCUMENT_CATEGORIES.map((c) => (
          <ToggleGroupItem key={c} value={c}>
            {t(`tripDetail.docCategory.${c}`)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <div className="flex gap-2">
        <Input
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          placeholder={t('tripDetail.docNote')}
          maxLength={2000}
        />
        <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending} className="shrink-0">
          <Check className="mr-2 h-4 w-4" />
          {t('common.save')}
        </Button>
      </div>
    </div>
  );
}
