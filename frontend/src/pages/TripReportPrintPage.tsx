import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { tripReportsApi } from '@/lib/tripReports';
import { tripsApi } from '@/lib/trips';
import { TripExpenseReportTables } from '@/components/trips/TripExpenseReportTables';

/**
 * Standalone print view (no dashboard shell/sidebar) so "Print" / "Save as PDF"
 * in the browser produces a clean page mirroring the original paper form.
 */
export default function TripReportPrintPage() {
  const { id = '' } = useParams<{ id: string }>();
  const { t } = useTranslation();

  const tripQuery = useQuery({
    queryKey: ['trip', id],
    queryFn: () => tripsApi.get(id),
    enabled: Boolean(id),
  });
  const reportQuery = useQuery({
    queryKey: ['trip', id, 'report'],
    queryFn: () => tripReportsApi.get(id),
    enabled: Boolean(id),
  });

  const trip = tripQuery.data;
  const report = reportQuery.data;
  const isLoading = reportQuery.isLoading || tripQuery.isLoading;
  const isError = reportQuery.isError || tripQuery.isError;

  return (
    <div className="mx-auto max-w-4xl bg-white p-6 text-black print:p-0">
      <style>{`
        @media print {
          @page { margin: 12mm; }
          body { background: white; }
          table { break-inside: auto; }
          tr, td, th { break-inside: avoid; }
          thead { display: table-header-group; }
          table, th, td {
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
            color-adjust: exact;
          }
        }
      `}</style>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold">
          {t('tripReport.title')} {trip ? `— ${trip.reference}` : ''}
        </h1>
        <button
          type="button"
          onClick={() => window.print()}
          className="rounded border border-black px-3 py-1 text-sm print:hidden"
        >
          {t('tripReport.print')}
        </button>
      </div>

      {isLoading ? (
        <p>…</p>
      ) : isError ? (
        <p className="text-red-600">{t('tripReport.error')}</p>
      ) : !report ? (
        <p>{t('tripReport.empty')}</p>
      ) : (
        <TripExpenseReportTables report={report} />
      )}
    </div>
  );
}
