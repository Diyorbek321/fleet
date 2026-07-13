import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';

import type { TripExpenseReport, TripReportCountry, TripReportExpenseCategory } from '@/lib/tripReports';

const COUNTRY_CATEGORIES: Record<TripReportCountry, TripReportExpenseCategory[]> = {
  kz: ['platon', 'food', 'traffic_police', 'adblue', 'fine', 'spare_parts', 'repair', 'refund', 'parking', 'phone', 'transport', 'shower'],
  ru: ['platon', 'food', 'traffic_police', 'adblue', 'fine', 'spare_parts', 'repair', 'refund', 'parking', 'phone', 'transport', 'shower'],
  uz: ['groceries', 'fine', 'spare_parts', 'parking_paperwork', 'food', 'taxi', 'carwash', 'repair', 'refund'],
};

const FUEL_COLUMNS = ['kz', 'rf', 'doha', 'e1card'] as const;

function fmt(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n.toLocaleString() : '—';
}

function fmtDate(v: string | null): string {
  if (!v) return '—';
  return new Date(v).toLocaleString();
}

/** Pure presentational render of a trip expense report, laid out to mirror the paper form. Shared by the manager card and the print page. */
export function TripExpenseReportTables({ report }: { report: TripExpenseReport }) {
  const { t } = useTranslation();
  const th = (k: string) => t(`tripReport.${k}`);

  const categoryLabel = (c: TripReportExpenseCategory) => {
    const key = c.replace(/_([a-z])/g, (_, ch: string) => ch.toUpperCase());
    return t(`tripReport.countries.category.${key}`);
  };

  const amountFor = (country: TripReportCountry, category: TripReportExpenseCategory) =>
    report.countryExpenses.find((l) => l.country === country && l.category === category)?.amount ?? null;

  return (
    <div className="space-y-6 text-sm">
      {/* Header */}
      <section>
        <h3 className="mb-2 font-semibold">{th('header.title')}</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label={th('header.plate')} value={report.plateNumber} />
          <Field label={th('header.driverName')} value={report.driverName} />
          <Field label={th('header.date')} value={report.reportDate} />
          <Field label={th('header.route')} value={report.routeText} />
          <Field label={th('header.odometerOut')} value={fmt(report.odometerOut)} />
          <Field label={th('header.odometerIn')} value={fmt(report.odometerIn)} />
          <Field label={th('header.fuelAtGarage')} value={fmt(report.fuelAtGarage)} />
          <Field label={th('header.exchangeNote')} value={report.exchangeRateNote} />
        </div>
      </section>

      {/* Money issued */}
      <section>
        <h3 className="mb-2 font-semibold">{th('money.title')}</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label={th('money.usd')} value={fmt(report.moneyUsd)} />
          <Field label={th('money.rub')} value={fmt(report.moneyRub)} />
          <Field label={th('money.kzt')} value={fmt(report.moneyKzt)} />
          <Field label={th('money.uzs')} value={fmt(report.moneyUzs)} />
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label={`${th('money.toKzt')} (${th('money.given')})`} value={fmt(report.usdToKztGiven)} />
          <Field label={`${th('money.toKzt')} (${th('money.received')})`} value={fmt(report.usdToKztReceived)} />
          <Field label={`${th('money.toRub')} (${th('money.given')})`} value={fmt(report.usdToRubGiven)} />
          <Field label={`${th('money.toRub')} (${th('money.received')})`} value={fmt(report.usdToRubReceived)} />
        </div>
      </section>

      {/* Fuel table */}
      <section>
        <h3 className="mb-2 font-semibold">{th('fuel.title')}</h3>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse border border-border text-xs sm:text-sm print:[-webkit-print-color-adjust:exact] print:[print-color-adjust:exact]">
            <thead>
              <tr className="bg-muted print:break-inside-avoid print:[-webkit-print-color-adjust:exact] print:[print-color-adjust:exact]">
                <th className="border border-border p-1">{th('fuel.row')}</th>
                {FUEL_COLUMNS.map((c) => (
                  <th key={c} className="border border-border p-1" colSpan={2}>
                    {th(`fuel.${c}`)}
                  </th>
                ))}
              </tr>
              <tr className="bg-muted/50 print:break-inside-avoid print:[-webkit-print-color-adjust:exact] print:[print-color-adjust:exact]">
                <th className="border border-border p-1" />
                {FUEL_COLUMNS.map((c) => (
                  <Fragment key={c}>
                    <th className="border border-border p-1">{th('fuel.liters')}</th>
                    <th className="border border-border p-1">{th('fuel.amount')}</th>
                  </Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.fuelRows.map((row) => (
                <tr key={row.rowNo} className="print:break-inside-avoid">
                  <td className="border border-border p-1 text-center">{row.rowNo}</td>
                  <td className="border border-border p-1 text-right">{fmt(row.kzLiters)}</td>
                  <td className="border border-border p-1 text-right">{fmt(row.kzAmount)}</td>
                  <td className="border border-border p-1 text-right">{fmt(row.rfLiters)}</td>
                  <td className="border border-border p-1 text-right">{fmt(row.rfAmount)}</td>
                  <td className="border border-border p-1 text-right">{fmt(row.dohaLiters)}</td>
                  <td className="border border-border p-1 text-right">{fmt(row.dohaAmount)}</td>
                  <td className="border border-border p-1 text-right">{fmt(row.e1cardLiters)}</td>
                  <td className="border border-border p-1 text-right">{fmt(row.e1cardAmount)}</td>
                </tr>
              ))}
              <tr className="font-semibold print:break-inside-avoid">
                <td className="border border-border p-1 text-center">{th('fuel.total')}</td>
                {FUEL_COLUMNS.map((c) => (
                  <Fragment key={c}>
                    <td className="border border-border p-1 text-right">
                      {fmt(report.totals.fuelByColumn[c]?.liters)}
                    </td>
                    <td className="border border-border p-1 text-right">
                      {fmt(report.totals.fuelByColumn[c]?.amount)}
                    </td>
                  </Fragment>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Border crossing */}
      <section>
        <h3 className="mb-2 font-semibold">{th('border.title')}</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label={th('border.departure')} value={fmtDate(report.borderDepartureAt)} />
          <Field label={th('border.arrival')} value={fmtDate(report.borderArrivalAt)} />
          <Field label={th('border.electronicPass')} value={report.electronicPassNote} />
          <Field label={th('border.electronicQueue')} value={report.electronicQueueNote} />
        </div>
      </section>

      {/* Per-country expenses */}
      <section>
        <h3 className="mb-2 font-semibold">{th('countries.title')}</h3>
        <div className="grid gap-4 sm:grid-cols-3">
          {(['kz', 'ru', 'uz'] as TripReportCountry[]).map((country) => (
            <div key={country}>
              <table className="w-full border-collapse border border-border text-xs sm:text-sm print:[-webkit-print-color-adjust:exact] print:[print-color-adjust:exact]">
                <thead>
                  <tr className="bg-muted print:break-inside-avoid print:[-webkit-print-color-adjust:exact] print:[print-color-adjust:exact]">
                    <th className="border border-border p-1 text-left" colSpan={2}>
                      {th(`countries.${country}`)}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {COUNTRY_CATEGORIES[country].map((cat) => (
                    <tr key={cat} className="print:break-inside-avoid">
                      <td className="border border-border p-1">{categoryLabel(cat)}</td>
                      <td className="border border-border p-1 text-right">{fmt(amountFor(country, cat))}</td>
                    </tr>
                  ))}
                  <tr className="font-semibold print:break-inside-avoid">
                    <td className="border border-border p-1">{th('countries.subtotal')}</td>
                    <td className="border border-border p-1 text-right">
                      {fmt(report.totals.countryTotals[country])}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <section>
        <h3 className="mb-2 font-semibold">{th('footer.title')}</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label={th('footer.insuranceRf')} value={fmt(report.insuranceRf)} />
          <Field label={th('footer.insuranceKz')} value={fmt(report.insuranceKz)} />
          <Field label={th('footer.dollarReturn')} value={fmt(report.dollarReturn)} />
        </div>
        {report.driverComment && (
          <p className="mt-2">
            <span className="font-medium">{th('footer.comment')}: </span>
            {report.driverComment}
          </p>
        )}
      </section>

      {/* Currency balances */}
      <section>
        <h3 className="mb-1 font-semibold">{th('balances.title')}</h3>
        <p className="mb-2 text-xs text-muted-foreground">{th('balances.hint')}</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label={th('money.usd')} value={fmt(report.totals.currencyBalances.usd)} />
          <Field label={th('money.rub')} value={fmt(report.totals.currencyBalances.rub)} />
          <Field label={th('money.kzt')} value={fmt(report.totals.currencyBalances.kzt)} />
          <Field label={th('money.uzs')} value={fmt(report.totals.currencyBalances.uzs)} />
        </div>
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium">{value ?? '—'}</div>
    </div>
  );
}
