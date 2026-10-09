import { describe, it, expect } from 'vitest';
import { DRIVER_COLUMNS, TRUCK_COLUMNS, needsAttention, nearestDocumentDays, summarizeDocuments } from './documents';

const TODAY = '2026-10-09';

describe('document columns', () => {
  it('lists the three policies then the rig papers', () => {
    expect(TRUCK_COLUMNS.map((c) => c.field)).toEqual([
      'insuranceExpiry',
      'insuranceExpiryKz',
      'insuranceExpiryRf',
      'inspectionExpiry',
      'permitExpiry',
      'transportLicenseExpiry',
      'certificateExpiry',
      'tachographExpiry',
    ]);
  });

  it('lists the five driver papers', () => {
    expect(DRIVER_COLUMNS).toHaveLength(5);
  });
});

describe('summarizeDocuments', () => {
  it('counts each document of each row', () => {
    const rows = [
      { passportExpiry: '2026-10-01', licenseExpiry: '2026-10-20' },
      { passportExpiry: '2030-01-01' },
    ];
    const s = summarizeDocuments(rows, DRIVER_COLUMNS, TODAY);
    expect(s.expired).toBe(1);
    expect(s.soon).toBe(1);
    // 5 columns × 2 rows − 3 dated.
    expect(s.missing).toBe(7);
  });
});

describe('needsAttention / nearestDocumentDays', () => {
  it('flags a row with a document inside the month', () => {
    expect(needsAttention({ chipCardExpiry: '2026-10-30' }, DRIVER_COLUMNS, TODAY)).toBe(true);
    expect(needsAttention({ chipCardExpiry: '2027-10-30' }, DRIVER_COLUMNS, TODAY)).toBe(false);
    expect(needsAttention({}, DRIVER_COLUMNS, TODAY)).toBe(false);
  });

  it('returns the nearest date, or null with none entered', () => {
    expect(
      nearestDocumentDays({ inspectionExpiry: '2026-10-19', tachographExpiry: '2026-10-12' }, TRUCK_COLUMNS, TODAY),
    ).toBe(3);
    expect(nearestDocumentDays({}, TRUCK_COLUMNS, TODAY)).toBeNull();
  });
});
