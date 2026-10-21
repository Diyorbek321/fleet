import { describe, expect, it } from 'vitest';
import { placeKey, placesForStage, toBody } from './trips';

describe('toBody', () => {
  it('drops blanks on create', () => {
    expect(
      toBody({ customsPoint: 'ТАШКЕНТ ТОВАРНЫЙ', declarantContact: null, loadingAddress: '' }, 'create'),
    ).toEqual({ customs_point: 'ТАШКЕНТ ТОВАРНЫЙ' });
  });

  it('sends blanks as null on an edit, so a field can be cleared', () => {
    expect(
      toBody({ customsPoint: 'ЧУКУРСАЙ', declarantContact: '', truckId: null }, 'update'),
    ).toEqual({ customs_point: 'ЧУКУРСАЙ', declarant_contact: null, truck_id: null });
  });

  it('leaves out what the caller did not pass', () => {
    expect(toBody({ driverId: 'd1' }, 'update')).toEqual({ driver_id: 'd1' });
  });
});

describe('placesForStage', () => {
  it('names a crossing for border stages', () => {
    expect(placesForStage('arrived_border')).toEqual(['uz_kz', 'kz_ru']);
    expect(placesForStage('crossed_border')).toEqual(['uz_kz', 'kz_ru']);
  });

  it('reads a crossing in the order a southbound run meets it', () => {
    expect(placeKey('kz_ru', 'ru_uz')).toBe('trips.placeSouthbound.kz_ru');
    expect(placeKey('kz_ru', 'uz_ru')).toBe('trips.place.kz_ru');
    expect(placeKey('ru', 'ru_uz')).toBe('trips.place.ru');
    expect(placeKey('uz_kz', null)).toBe('trips.place.uz_kz');
  });

  it('names a country for everything else', () => {
    expect(placesForStage('arrived_customs')).toEqual(['uz', 'kz', 'ru']);
  });
});
