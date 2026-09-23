import React, { createContext, useContext, useMemo, useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Truck, DashboardStats } from '@/types';
import { trucksApi, calculateStats } from '@/lib/trucks';
import { ApiError } from '@/lib/api';
import { statusFromSpeed } from '@/lib/locations';
import { useLiveLocations } from '@/hooks/useLiveLocations';
import { fetchTruckLocationLabels } from '@/lib/locations';
import { toast } from '@/hooks/use-toast';
import i18n from '@/i18n';

type NewTruckInput = Omit<Truck, 'id' | 'status' | 'speed' | 'latitude' | 'longitude' | 'lastUpdate'>;

interface TruckContextType {
  trucks: Truck[];
  stats: DashboardStats;
  isLoading: boolean;
  selectedTruck: Truck | null;
  setSelectedTruck: (truck: Truck | null) => void;
  addTruck: (truck: NewTruckInput) => Promise<void>;
  updateTruck: (id: string, data: Partial<Truck>) => Promise<void>;
  removeTruck: (id: string) => Promise<void>;
  toggleTruckEnabled: (id: string) => Promise<void>;
  refreshTrucks: () => Promise<void>;
}

const TruckContext = createContext<TruckContextType | undefined>(undefined);

const TRUCKS_KEY = ['trucks'] as const;
const TRUCK_PLACE_LABELS_KEY = ['truck-place-labels'] as const;

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

export function TruckProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [selectedTruck, setSelectedTruck] = useState<Truck | null>(null);

  const { data: baseTrucks = [], isLoading } = useQuery({
    queryKey: TRUCKS_KEY,
    queryFn: trucksApi.list,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const { locations } = useLiveLocations();

  // Place names ("Qozog'iston, Sariog'ash") are polled on their own rather than
  // taken from the live stream: the WebSocket is authoritative for position and
  // carries no address, and the backend relabels positions every 5 minutes.
  const { data: placeLabels = {} } = useQuery({
    queryKey: TRUCK_PLACE_LABELS_KEY,
    queryFn: fetchTruckLocationLabels,
    refetchInterval: 300_000,
    staleTime: 120_000,
  });

  const trucks = useMemo<Truck[]>(
    () =>
      baseTrucks.map((t) => {
        const live = locations[t.id];
        const address = placeLabels[t.id] ?? live?.address ?? t.address ?? null;
        if (!live) return address === t.address ? t : { ...t, address };
        return {
          ...t,
          latitude: live.latitude,
          longitude: live.longitude,
          speed: live.speed,
          status: statusFromSpeed(live.speed),
          address,
          lastUpdate: live.recordedAt,
        };
      }),
    [baseTrucks, locations, placeLabels],
  );

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: TRUCKS_KEY }),
    [queryClient],
  );

  const createMutation = useMutation({
    mutationFn: trucksApi.create,
    onSuccess: (truck) => {
      invalidate();
      toast({
        title: i18n.t('trucks.toast.added'),
        description: i18n.t('trucks.toast.addedBody', { name: truck.name }),
      });
    },
    onError: (err) => {
      toast({
        title: i18n.t('trucks.toast.addFailed'),
        description: errorMessage(err, i18n.t('common.tryAgain')),
        variant: 'destructive',
      });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Parameters<typeof trucksApi.update>[1] }) =>
      trucksApi.update(id, patch),
    onSuccess: () => {
      invalidate();
    },
    onError: (err) => {
      toast({
        title: i18n.t('trucks.toast.updateFailed'),
        description: errorMessage(err, i18n.t('common.tryAgain')),
        variant: 'destructive',
      });
    },
  });

  const removeMutation = useMutation({
    mutationFn: trucksApi.remove,
    onSuccess: () => {
      invalidate();
      toast({
        title: i18n.t('trucks.toast.deleted'),
        description: i18n.t('trucks.toast.deletedBody'),
      });
    },
    onError: (err) => {
      toast({
        title: i18n.t('trucks.toast.deleteFailed'),
        description: errorMessage(err, i18n.t('common.tryAgain')),
        variant: 'destructive',
      });
    },
  });

  const addTruck = useCallback(
    async (input: NewTruckInput) => {
      await createMutation.mutateAsync({
        name: input.name,
        plateNumber: input.plateNumber,
        model: input.model,
        tractorBrand: input.tractorBrand,
        trailerBrand: input.trailerBrand,
        trailerVolume: input.trailerVolume,
      });
    },
    [createMutation],
  );

  const updateTruck = useCallback(
    async (id: string, data: Partial<Truck>) => {
      await updateMutation.mutateAsync({
        id,
        patch: {
          name: data.name,
          plateNumber: data.plateNumber,
          model: data.model,
          tractorBrand: data.tractorBrand,
          trailerBrand: data.trailerBrand,
          trailerVolume: data.trailerVolume,
        },
      });
      toast({
        title: i18n.t('trucks.toast.updated'),
        description: i18n.t('trucks.toast.updatedBody'),
      });
    },
    [updateMutation],
  );

  const removeTruck = useCallback(
    async (id: string) => {
      await removeMutation.mutateAsync(id);
    },
    [removeMutation],
  );

  const toggleTruckEnabled = useCallback(
    async (id: string) => {
      const current = trucks.find((t) => t.id === id);
      if (!current) return;
      const nextStatus = current.isEnabled ? 'offline' : 'stopped';
      await updateMutation.mutateAsync({ id, patch: { status: nextStatus } });
      toast({
        title: current.isEnabled ? i18n.t('trucks.toast.disabled') : i18n.t('trucks.toast.enabled'),
        description: current.isEnabled
          ? i18n.t('trucks.toast.disabledBody', { name: current.name })
          : i18n.t('trucks.toast.enabledBody', { name: current.name }),
      });
    },
    [trucks, updateMutation],
  );

  const refreshTrucks = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: TRUCKS_KEY });
  }, [queryClient]);

  const stats = useMemo(() => calculateStats(trucks), [trucks]);

  const value = useMemo<TruckContextType>(
    () => ({
      trucks,
      stats,
      isLoading,
      selectedTruck,
      setSelectedTruck,
      addTruck,
      updateTruck,
      removeTruck,
      toggleTruckEnabled,
      refreshTrucks,
    }),
    [
      trucks,
      stats,
      isLoading,
      selectedTruck,
      addTruck,
      updateTruck,
      removeTruck,
      toggleTruckEnabled,
      refreshTrucks,
    ],
  );

  return <TruckContext.Provider value={value}>{children}</TruckContext.Provider>;
}

export function useTrucks(): TruckContextType {
  const ctx = useContext(TruckContext);
  if (ctx === undefined) throw new Error('useTrucks must be used within a TruckProvider');
  return ctx;
}
