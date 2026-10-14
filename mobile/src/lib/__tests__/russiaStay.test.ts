import { stayLevel, type StaySummary } from '../russiaStay';

const inside = (days_to_leave: number, overstay_days = 0): StaySummary => ({
  in_russia: true,
  entered_on: '2026-08-29',
  day_of_stay: 47,
  days_used: 47,
  days_available: 43,
  must_leave_by: '2026-11-26',
  days_to_leave,
  overstay_days,
});

describe('how loudly the Russia card speaks', () => {
  it('stays calm with weeks to go', () => {
    expect(stayLevel(inside(43))).toBe('ok');
  });

  it('warns inside the same 15 and 3 days the reminders use', () => {
    expect(stayLevel(inside(15))).toBe('soon');
    expect(stayLevel(inside(3))).toBe('urgent');
    expect(stayLevel(inside(0))).toBe('urgent');
  });

  it('says overstay once past the deadline', () => {
    expect(stayLevel(inside(-2, 2))).toBe('over');
  });

  it('is silent outside Russia', () => {
    expect(stayLevel({ ...inside(10), in_russia: false, days_to_leave: null })).toBe('ok');
  });
});
