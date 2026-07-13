import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { FileText, Printer } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { tripReportsApi } from '@/lib/tripReports';
import { TripExpenseReportTables } from '@/components/trips/TripExpenseReportTables';

export function TripExpenseReportCard({ tripId }: { tripId: string }) {
  const { t } = useTranslation();

  const reportQuery = useQuery({
    queryKey: ['trip', tripId, 'report'],
    queryFn: () => tripReportsApi.get(tripId),
    enabled: Boolean(tripId),
  });

  const report = reportQuery.data;

  return (
    <Card className="border-border/50 bg-card">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-lg">
            <FileText className="h-5 w-5" />
            {t('tripReport.title')}
            {report && (
              <Badge variant={report.status === 'submitted' ? 'default' : 'outline'}>
                {t(`tripReport.status.${report.status}`)}
              </Badge>
            )}
          </CardTitle>
          {report && (
            <Button variant="outline" size="sm" className="gap-1" asChild>
              <a href={`/trips/${tripId}/report/print`} target="_blank" rel="noreferrer">
                <Printer className="h-4 w-4" />
                {t('tripReport.print')}
              </a>
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {reportQuery.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : !report ? (
          <p className="py-6 text-center text-sm text-muted-foreground">{t('tripReport.empty')}</p>
        ) : (
          <TripExpenseReportTables report={report} />
        )}
      </CardContent>
    </Card>
  );
}
