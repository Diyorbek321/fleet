import {
  placesFor,
  suggestedStages,
  TRIP_STAGES,
  type StagePlace,
  type TripStage,
} from '../trips';

describe('where a stage can have happened', () => {
  it('offers a crossing at a border, never a bare country', () => {
    // "На границе КЗ" does not say whether the truck is leaving Uzbekistan or
    // entering Russia, and those are four days apart on the same trip.
    for (const stage of ['arrived_border', 'crossed_border'] as TripStage[]) {
      expect(placesFor(stage)).toEqual(['uz_kz', 'kz_ru']);
    }
  });

  it('offers a country everywhere else', () => {
    const countries: StagePlace[] = ['uz', 'kz', 'ru'];
    for (const stage of TRIP_STAGES) {
      if (stage === 'arrived_border' || stage === 'crossed_border') continue;
      expect(placesFor(stage)).toEqual(countries);
    }
  });
});

describe('what to suggest next', () => {
  it('puts the step that usually follows at the top', () => {
    expect(suggestedStages('arrived_loading')[0]).toBe('loaded_waiting_docs');
    expect(suggestedStages('crossed_border')[0]).toBe('arrived_customs');
  });

  it('still offers every stage, because real runs skip and repeat steps', () => {
    // A driver who cannot report what actually happened stops reporting at all.
    for (const stage of TRIP_STAGES) {
      expect(suggestedStages(stage).sort()).toEqual([...TRIP_STAGES].sort());
    }
  });

  it('keeps a border reachable again after it was just crossed', () => {
    // Tashkent–Tobolsk crosses two borders; the second must not be buried.
    expect(suggestedStages('crossed_border')).toContain('arrived_border');
  });

  it('offers the whole list in order when nothing has been reported yet', () => {
    expect(suggestedStages(null)).toEqual(TRIP_STAGES);
  });
});
