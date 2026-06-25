import { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNow } from 'date-fns';
import { AlertTriangle, Check, Eye, Truck as TruckIcon, User, ExternalLink } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from '@/hooks/use-toast';
import {
  driverDataApi,
  type MaintenanceRequest,
  type MaintenanceRequestStatus,
} from '@/lib/driverData';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';

const REQUESTS_KEY = ['maintenance-requests'] as const;

const statusBadge: Record<MaintenanceRequestStatus, string> = {
  open: 'bg-destructive/20 text-destructive border-destructive/30',
  acknowledged: 'bg-status-stopped/20 text-status-stopped border-status-stopped/30',
  resolved: 'bg-status-moving/20 text-status-moving border-status-moving/30',
};

function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
}

export function DriverRequests() {
  const queryClient = useQueryClient();

  const { data: requests = [], isLoading } = useQuery({
    queryKey: REQUESTS_KEY,
    queryFn: () => driverDataApi.maintenanceRequests(),
    refetchInterval: 30_000,
  });

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: MaintenanceRequestStatus }) =>
      driverDataApi.updateRequestStatus(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: REQUESTS_KEY });
      toast({ title: 'Request updated' });
    },
    onError: (err) =>
      toast({ title: 'Update failed', description: describeError(err), variant: 'destructive' }),
  });

  const openCount = useMemo(() => requests.filter((r) => r.status === 'open').length, [requests]);

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
    );
  }

  if (requests.length === 0) {
    return (
      <Card className="border-border/50 bg-card">
        <CardContent className="py-12 text-center text-muted-foreground">
          No issues reported by drivers yet.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Issues reported by drivers from the mobile app.
        {openCount > 0 && (
          <span className="ml-1 font-medium text-destructive">{openCount} open.</span>
        )}
      </p>

      {requests.map((req: MaintenanceRequest) => (
        <Card key={req.id} className="border-border/50 bg-card">
          <CardContent className="p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{req.title}</span>
                  <Badge variant="outline" className={cn('capitalize', statusBadge[req.status])}>
                    {req.status}
                  </Badge>
                </div>
                {req.description && (
                  <p className="text-sm text-muted-foreground">{req.description}</p>
                )}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <User className="h-3 w-3" /> {req.driverName ?? 'Unknown driver'}
                  </span>
                  <span className="flex items-center gap-1">
                    <TruckIcon className="h-3 w-3" /> {req.truckPlate ?? '—'}
                  </span>
                  <span>{formatDistanceToNow(new Date(req.createdAt), { addSuffix: true })}</span>
                  {req.photoUrl && (
                    <a
                      href={req.photoUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-primary hover:underline"
                    >
                      <ExternalLink className="h-3 w-3" /> Photo
                    </a>
                  )}
                </div>
              </div>

              <div className="flex shrink-0 gap-2">
                {req.status === 'open' && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={updateStatus.isPending}
                    onClick={() => updateStatus.mutate({ id: req.id, status: 'acknowledged' })}
                  >
                    <Eye className="mr-1.5 h-3.5 w-3.5" /> Acknowledge
                  </Button>
                )}
                {req.status !== 'resolved' && (
                  <Button
                    size="sm"
                    disabled={updateStatus.isPending}
                    onClick={() => updateStatus.mutate({ id: req.id, status: 'resolved' })}
                  >
                    <Check className="mr-1.5 h-3.5 w-3.5" /> Resolve
                  </Button>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
