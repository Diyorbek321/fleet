import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  Boxes,
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
  ShieldCheck,
  SatelliteDish,
} from 'lucide-react';
import { formatDistanceToNow } from '@/lib/datetime';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { CountryExpenseReportCard } from '@/components/reports/CountryExpenseReportCard';
import { TruckFormModal } from '@/components/trucks/TruckFormModal';
import { TruckTelegramGroupCard } from '@/components/trucks/TruckTelegramGroupCard';
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
  const { t } = useTranslation();
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
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('trucks.detail.back')}
        </Button>
        <p className="text-muted-foreground">{t('trucks.detail.notFound')}</p>
      </div>
    );
  }

  // The edit modal works against the flattened `Truck` map model.
  const editTruck: Truck = {
    id: truck.id,
    plateNumber: truck.plateNumber,
    name: truck.name,
    model: truck.model ?? undefined,
    tractorBrand: truck.tractorBrand ?? undefined,
    trailerBrand: truck.trailerBrand ?? undefined,
    trailerVolume: truck.trailerVolume ?? undefined,
    insuranceExpiry: truck.insuranceExpiry,
    driverName: truck.driver?.name,
    status: truck.status === 'moving' ? 'moving' : truck.status === 'offline' ? 'offline' : 'stopped',
    speed: truck.location?.speed ?? 0,
    latitude: truck.location?.latitude ?? 0,
    longitude: truck.location?.longitude ?? 0,
    lastUpdate: truck.updatedAt,
    isEnabled: truck.isEnabled,
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate('/trucks')} title={t('trucks.detail.back')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight">{truck.plateNumber}</h1>
              <Badge variant="outline" className={cn(statusBadgeClasses[truck.status])}>
                {t(`trucks.status.${truck.status}`, { defaultValue: truck.status })}
              </Badge>
              {truck.gpsDisabledAt && (
                <Badge
                  variant="outline"
                  className="border-destructive/30 bg-destructive/10 text-destructive"
                  title={formatDistanceToNow(truck.gpsDisabledAt, { addSuffix: true })}
                >
                  <SatelliteDish className="mr-1 h-3.5 w-3.5" /> {t('trucks.detail.gpsOff')}
                </Badge>
              )}
            </div>
            <p className="text-muted-foreground">{truck.name}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate(`/map?truck=${truck.id}`)}>
            <MapPin className="mr-2 h-4 w-4" /> {t('trucks.viewOnMap')}
          </Button>
          <Button onClick={() => setIsEditOpen(true)}>
            <Pencil className="mr-2 h-4 w-4" /> {t('common.edit')}
          </Button>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Vehicle info */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <TruckIcon className="h-5 w-5" /> {t('trucks.detail.vehicle')}
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-border/50">
            <InfoRow icon={<TruckIcon className="h-4 w-4" />} label={t('trucks.form.tractorBrand')}>
              {truck.tractorBrand || '—'}
            </InfoRow>
            <InfoRow icon={<TruckIcon className="h-4 w-4" />} label={t('trucks.form.trailerBrand')}>
              {truck.trailerBrand || '—'}
            </InfoRow>
            <InfoRow icon={<Boxes className="h-4 w-4" />} label={t('trucks.form.trailerVolume')}>
              {truck.trailerVolume ? t(`trucks.volume.${truck.trailerVolume}`) : '—'}
            </InfoRow>
            <InfoRow icon={<ShieldCheck className="h-4 w-4" />} label={t('trucks.form.insuranceExpiry')}>
              {truck.insuranceExpiry ? (
                <span
                  className={
                    truck.insuranceExpiry < new Date().toISOString().slice(0, 10)
                      ? 'text-destructive'
                      : undefined
                  }
                >
                  {new Date(truck.insuranceExpiry).toLocaleDateString()}
                </span>
              ) : (
                '—'
              )}
            </InfoRow>
            {/* The model is no longer asked for; kept where it was entered. */}
            {truck.model && (
              <InfoRow icon={<TruckIcon className="h-4 w-4" />} label={t('trucks.detail.model')}>
                {truck.model}
                {truck.year ? ` (${truck.year})` : ''}
              </InfoRow>
            )}
            <InfoRow icon={<Gauge className="h-4 w-4" />} label={t('trucks.detail.mileage')}>
              {truck.mileage.toLocaleString()} {t('common.km')}
            </InfoRow>
            <div className="py-3">
              <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                <Fuel className="h-4 w-4" /> {t('trucks.detail.fuelLevel')}
              </div>
              <div className="flex items-center gap-3">
                <Progress value={truck.fuelLevel} className="h-2 flex-1" />
                <span className="w-12 text-right text-sm font-medium">
                  {Math.round(truck.fuelLevel)}%
                </span>
              </div>
            </div>
            <InfoRow icon={<Clock className="h-4 w-4" />} label={t('trucks.detail.lastUpdated')}>
              {formatDistanceToNow(truck.updatedAt, { addSuffix: true })}
            </InfoRow>
          </CardContent>
        </Card>

        {/* Driver info */}
        <Card className="border-border/50 bg-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <User className="h-5 w-5" /> {t('trucks.detail.assignedDriver')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {truck.driver ? (
              <div className="divide-y divide-border/50">
                <InfoRow icon={<User className="h-4 w-4" />} label={t('drivers.name')}>
                  <Link
                    to={`/drivers/${truck.driver.id}`}
                    className="text-primary hover:underline"
                  >
                    {truck.driver.name}
                  </Link>
                </InfoRow>
                <InfoRow icon={<Phone className="h-4 w-4" />} label={t('drivers.phone')}>
                  {truck.driver.phone || '—'}
                </InfoRow>
                <InfoRow icon={<Mail className="h-4 w-4" />} label={t('drivers.email')}>
                  {truck.driver.email || '—'}
                </InfoRow>
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t('trucks.detail.noDriver')}
              </p>
            )}
          </CardContent>
        </Card>

        <TruckTelegramGroupCard truckId={truck.id} />

        {/* Last known location */}
        <Card className="border-border/50 bg-card md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <MapPin className="h-5 w-5" /> {t('trucks.detail.lastLocation')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {truck.location ? (
              <div className="grid gap-x-8 sm:grid-cols-2">
                <InfoRow icon={<MapPin className="h-4 w-4" />} label={t('trucks.detail.coordinates')}>
                  <span className="font-mono">
                    {truck.location.latitude.toFixed(5)}, {truck.location.longitude.toFixed(5)}
                  </span>
                </InfoRow>
                <InfoRow icon={<MapPin className="h-4 w-4" />} label={t('trucks.detail.address')}>
                  {truck.location.address || '—'}
                </InfoRow>
                <InfoRow icon={<Gauge className="h-4 w-4" />} label={t('trucks.colSpeed')}>
                  {Math.round(truck.location.speed)} {t('common.kmh')}
                </InfoRow>
                <InfoRow icon={<Navigation className="h-4 w-4" />} label={t('trucks.detail.heading')}>
                  {truck.location.heading != null ? `${Math.round(truck.location.heading)}°` : '—'}
                </InfoRow>
                <InfoRow icon={<Clock className="h-4 w-4" />} label={t('trucks.detail.recorded')}>
                  {formatDistanceToNow(truck.location.recordedAt, { addSuffix: true })}
                </InfoRow>
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t('trucks.detail.noLocation')}
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
