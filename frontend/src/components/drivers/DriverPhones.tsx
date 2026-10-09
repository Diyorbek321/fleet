import { useTranslation } from 'react-i18next';

import { CopyButton } from '@/components/CopyButton';
import type { Driver } from '@/lib/drivers';

/** The SIM each slot holds: `phone` Uzbek, `phone2` Kazakh, `phone3` Russian. */
const SLOTS = [
  { field: 'phone', country: 'uz' },
  { field: 'phone2', country: 'kz' },
  { field: 'phone3', country: 'ru' },
] as const;

/**
 * A driver's numbers, each tagged with its country and copyable on its own:
 * the dispatcher pastes one at a time into a dialler or a chat, and which
 * country it is says whether the driver is reachable on it right now.
 */
export function DriverPhones({ driver }: { driver: Pick<Driver, 'phone' | 'phone2' | 'phone3'> }) {
  const { t } = useTranslation();
  const phones = SLOTS.map((slot) => ({ ...slot, number: driver[slot.field]?.trim() })).filter(
    (p): p is (typeof SLOTS)[number] & { number: string } => !!p.number,
  );
  if (phones.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <ul className="space-y-0.5">
      {phones.map(({ field, country, number }) => (
        <li key={field} className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="w-6 text-[10px] font-semibold uppercase text-muted-foreground">{country}</span>
          <span className="font-mono">{number}</span>
          <CopyButton text={number} label={t('drivers.copyPhone', { phone: number })} />
        </li>
      ))}
    </ul>
  );
}
