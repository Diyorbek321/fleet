import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  Pencil,
  MapPin,
  Gauge,
  Fuel,
  Navigation,
  Clock,
  User,
  Phone,
  Mail,
  Truck as TruckIcon,
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { CountryExpenseReportCard } from '@/components/reports/CountryExpenseReportCard';
import { TruckFormModal } from '@/components/trucks/TruckFormModal';
import { trucksApi } from '@/lib/trucks';
import type { Truck } from '@/types';
import { cn } from '@/lib/utils';

const statusBadgeClasses: Record<string, string> = {
  moving: 'bg-status-moving/20 text-status-moving border-status-moving/30',
  stopped: 'bg-status-stopped/20 text-status-stopped border-status-stopped/30',
  idle: 'bg-status-stopped/20 text-status-stopped border-status-stopped/30',
  offline: 'bg-status-offline/20 text-status-offline border-status-offline/30',
  maintenance: 'bg-muted text-muted-foreground border-border',
};

interface InfoRowProps {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}

function InfoRow({ icon, label, children }: InfoRowProps) {
  return (
    <div className="flex items-start gap-3 py-2">
      <span className="mt-0.5 text-muted-foreground">{icon}</span>
      <div className="flex-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="text-sm font-medium">{children}</div>
      </div>
    </div>
  );
}

export default function TruckDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [isEditOpen, setIsEditOpen] = useState(false);

  const { data: truck, isLoading, isError } = useQuery({
    queryKey: ['truck', id],
    queryFn: () => trucksApi.getDetails(id),
    enabled: Boolean(id),
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-40" />
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  if (isError || !truck) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" onClick={() => navigate('/trucks')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Trucks
        </Button>
        <p className="text-muted-foreground">Truck not found.</p>
      </div>
    );
  }

  // The edit modal works against the flattened `Truck` map model.
  const editTruck: Truck = {
    id: truck.id,
    plateNumber: truck.plateNumber,
    name: truck.name,
    deviceImei: '',
    model: truck.model ?? undefined,
    driverName: truck.driver?.name,
    status: truck.status === 'moving' ? 'moving' : truck.status === 'offline' ? 'offline' : 'stopped',
    speed: truck.location?.speed ?? 0,
    latitude: truck.location?.latitude ?? 0,
    longitude: truck.location?.longitude ?? 0,
    lastUpdate: truck.updatedAt,
    isEnabled: truck.status !== 'offline',
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate('/trucks')} title="Back to Trucks">
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight">{truck.plateNumber}</h1>
              <Badge variant="outline" className={cn('capitalize', statusBadgeClasses[truck.status])}>
                {truck.status}
              </Badge>
            </div>
            <p className="text-muted-foreground">{truck.name}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate(`/map?truck=${truck.id}`)}>
            <MapPin className="mr-2 h-4 w-4" /> View on map
          </Button>
          <Button onClick={() => setIsEditOpen(true)}>
            <Pencil className="mr-2 h-4 w-4" /> Edit
          </Button>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Vehicle info */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <TruckIcon className="h-5 w-5" /> Vehicle
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-border/50">
            <InfoRow icon={<TruckIcon className="h-4 w-4" />} label="Model">
              {truck.model || '—'}
              {truck.year ? ` (${truck.year})` : ''}
            </InfoRow>
            <InfoRow icon={<Gauge className="h-4 w-4" />} label="Mileage">
              {truck.mileage.toLocaleString()} km
            </InfoRow>
            <div className="py-3">
              <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                <Fuel className="h-4 w-4" /> Fuel level
              </div>
              <div className="flex items-center gap-3">
                <Progress value={truck.fuelLevel} className="h-2 flex-1" />
                <span className="w-12 text-right text-sm font-medium">
                  {Math.round(truck.fuelLevel)}%
                </span>
              </div>
            </div>
            <InfoRow icon={<Clock className="h-4 w-4" />} label="Last updated">
              {formatDistanceToNow(truck.updatedAt, { addSuffix: true })}
            </InfoRow>
          </CardContent>
        </Card>

        {/* Driver info */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <User className="h-5 w-5" /> Assigned Driver
            </CardTitle>
          </CardHeader>
          <CardContent>
            {truck.driver ? (
              <div className="divide-y divide-border/50">
                <InfoRow icon={<User className="h-4 w-4" />} label="Name">
                  <Link
                    to={`/drivers/${truck.driver.id}`}
                    className="text-primary hover:underline"
                  >
                    {truck.driver.name}
                  </Link>
                </InfoRow>
                <InfoRow icon={<Phone className="h-4 w-4" />} label="Phone">
                  {truck.driver.phone || '—'}
                </InfoRow>
                <InfoRow icon={<Mail className="h-4 w-4" />} label="Email">
                  {truck.driver.email || '—'}
                </InfoRow>
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No driver assigned to this truck.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Last known location */}
        <Card className="border-border/50 bg-card md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <MapPin className="h-5 w-5" /> Last Known Location
            </CardTitle>
          </CardHeader>
          <CardContent>
            {truck.location ? (
              <div className="grid gap-x-8 sm:grid-cols-2">
                <InfoRow icon={<MapPin className="h-4 w-4" />} label="Coordinates">
                  <span className="font-mono">
                    {truck.location.latitude.toFixed(5)}, {truck.location.longitude.toFixed(5)}
                  </span>
                </InfoRow>
                <InfoRow icon={<MapPin className="h-4 w-4" />} label="Address">
                  {truck.location.address || '—'}
                </InfoRow>
                <InfoRow icon={<Gauge className="h-4 w-4" />} label="Speed">
                  {Math.round(truck.location.speed)} km/h
                </InfoRow>
                <InfoRow icon={<Navigation className="h-4 w-4" />} label="Heading">
                  {truck.location.heading != null ? `${Math.round(truck.location.heading)}°` : '—'}
                </InfoRow>
                <InfoRow icon={<Clock className="h-4 w-4" />} label="Recorded">
                  {formatDistanceToNow(truck.location.recordedAt, { addSuffix: true })}
                </InfoRow>
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No location data reported yet.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* This lorry's own runs, split by country. Pinned to the truck, so the
          page never shows a picker for a question already answered. */}
      <CountryExpenseReportCard truckId={truck.id} />

      <TruckFormModal open={isEditOpen} onClose={() => setIsEditOpen(false)} truck={editTruck} />
    </div>
  );
}
