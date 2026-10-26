/**
 * Everything the dispatcher typed into a trip, laid out for the driver: they
 * used to see only the route and the cargo, and phoned the desk for the
 * loading address, the contact there and the customs post.
 */
import type { Trip } from '../trips';
import { mapsUrl, phoneIn, tripDetailSections } from '../tripDetails';

const t = (key: string) => key;

const trip = {
  id: 'x',
  reference: 'TR-1',
  status: 'en_route',
  direction: 'uz_ru',
  customer: 'Artel Logistics',
  shipper: 'Artel',
  consignee: 'OOO Vostok',
  origin_name: 'Ташкент',
  destination_name: 'Москва',
  border_crossing: 'Майский',
  loading_address: 'Ташкент, ул. Навои 1',
  loading_contact: 'Алишер +998 90 123 45 67',
  customs_point: 'Москва-Восточная',
  unloading_address: 'Москва, склад 4',
  declarant_contact: null,
  cargo_description: 'ДСП',
  cargo_weight_kg: 20000,
  is_reefer: false,
  is_loaded: true,
  scheduled_start: '2026-10-20T00:00:00Z',
  scheduled_end: null,
  notes: 'Pallets only',
} as unknown as Trip;

describe('tripDetailSections', () => {
  const sections = tripDetailSections(trip, t);
  const row = (key: string) => sections.flatMap((s) => s.rows).find((r) => r.key === key);

  it('shows the customer and every address and contact the desk entered', () => {
    expect(row('customer')?.value).toBe('Artel Logistics');
    expect(row('loadingAddress')?.value).toBe('Ташкент, ул. Навои 1');
    expect(row('customsPoint')?.value).toBe('Москва-Восточная');
    expect(row('unloadingAddress')?.value).toBe('Москва, склад 4');
  });

  it('leaves out what was never filled in rather than printing dashes', () => {
    expect(row('declarantContact')).toBeUndefined();
    expect(row('unloadingDate')).toBeUndefined();
  });

  it('gives the weight in tonnes, as freight is quoted', () => {
    expect(row('cargoWeight')?.value).toBe('20 t');
  });

  it('makes a contact with a phone number callable', () => {
    expect(row('loadingContact')?.phone).toBe('+998901234567');
  });

  it("keeps the desk's internal notes off the driver's screen", () => {
    expect(row('notes' as never)).toBeUndefined();
  });

  it('drops a section with nothing in it', () => {
    const bare = tripDetailSections(
      { ...trip, cargo_description: null, cargo_weight_kg: null } as Trip,
      t,
    );
    expect(bare.find((s) => s.key === 'cargo')).toBeUndefined();
  });
});

describe('phoneIn', () => {
  it('finds a number written with spaces or dashes', () => {
    expect(phoneIn('Bobur 90-123-45-67')).toBe('901234567');
    expect(phoneIn('+7 (912) 345-67-89')).toBe('+79123456789');
  });

  it('ignores text without one', () => {
    expect(phoneIn('ask at the gate')).toBeNull();
    expect(phoneIn('склад 4')).toBeNull();
  });
});

describe('navigation', () => {
  const sections = tripDetailSections(trip, t);
  const row = (key: string) => sections.flatMap((s) => s.rows).find((r) => r.key === key);

  it('offers to navigate to the loading, unloading and customs addresses', () => {
    expect(row('loadingAddress')?.navigable).toBe(true);
    expect(row('unloadingAddress')?.navigable).toBe(true);
    expect(row('customsPoint')?.navigable).toBe(true);
    expect(row('customer')?.navigable).toBeUndefined();
  });

  it('hands Android a geo: link any navigator can take', () => {
    expect(mapsUrl('Москва, склад 4', 'android')).toBe(
      'geo:0,0?q=' + encodeURIComponent('Москва, склад 4'),
    );
  });

  it('hands iOS an Apple Maps link', () => {
    expect(mapsUrl('Ташкент', 'ios')).toBe('maps:0,0?q=' + encodeURIComponent('Ташкент'));
  });
});
