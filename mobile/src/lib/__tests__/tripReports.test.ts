import {
  clearTripReportDraft,
  loadTripReportDraft,
  saveTripReportDraft,
} from '../tripReports';

interface SampleDraft {
  note: string;
  count: number;
}

describe('trip report draft persistence', () => {
  it('returns null when no draft has been saved for a trip', async () => {
    expect(await loadTripReportDraft('trip-without-a-draft')).toBeNull();
  });

  it('round-trips a saved draft, including the pending action', async () => {
    await saveTripReportDraft<SampleDraft>('trip-1', { note: 'hello', count: 3 }, 'save');

    const draft = await loadTripReportDraft<SampleDraft>('trip-1');
    expect(draft).not.toBeNull();
    expect(draft?.data).toEqual({ note: 'hello', count: 3 });
    expect(draft?.pendingAction).toBe('save');
    expect(typeof draft?.savedAt).toBe('string');
  });

  it('keeps drafts for different trips independent', async () => {
    await saveTripReportDraft<SampleDraft>('trip-a', { note: 'a', count: 1 }, null);
    await saveTripReportDraft<SampleDraft>('trip-b', { note: 'b', count: 2 }, 'submit');

    expect((await loadTripReportDraft<SampleDraft>('trip-a'))?.data).toEqual({ note: 'a', count: 1 });
    expect((await loadTripReportDraft<SampleDraft>('trip-b'))?.data).toEqual({ note: 'b', count: 2 });
    expect((await loadTripReportDraft<SampleDraft>('trip-b'))?.pendingAction).toBe('submit');
  });

  it('overwrites a previously saved draft for the same trip', async () => {
    await saveTripReportDraft<SampleDraft>('trip-2', { note: 'first', count: 1 }, 'save');
    await saveTripReportDraft<SampleDraft>('trip-2', { note: 'second', count: 2 }, null);

    const draft = await loadTripReportDraft<SampleDraft>('trip-2');
    expect(draft?.data).toEqual({ note: 'second', count: 2 });
    expect(draft?.pendingAction).toBeNull();
  });

  it('removes the draft on clear', async () => {
    await saveTripReportDraft<SampleDraft>('trip-3', { note: 'x', count: 0 }, 'submit');
    expect(await loadTripReportDraft<SampleDraft>('trip-3')).not.toBeNull();

    await clearTripReportDraft('trip-3');
    expect(await loadTripReportDraft<SampleDraft>('trip-3')).toBeNull();
  });

  it('clearing a trip with no draft is a harmless no-op', async () => {
    await expect(clearTripReportDraft('never-saved-trip')).resolves.toBeUndefined();
  });
});
