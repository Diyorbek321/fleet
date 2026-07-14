import React, { createContext, useContext, useMemo, useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Truck, DashboardStats } from '@/types';
import { trucksApi, calculateStats } from '@/lib/trucks';
import { ApiError } from '@/lib/api';
import { statusFromSpeed } from '@/lib/locations';
import { useLiveLocations } from '@/hooks/useLiveLocations';
import { toast } from '@/hooks/use-toast';

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

  const trucks = useMemo<Truck[]>(
    () =>
      baseTrucks.map((t) => {
        const live = locations[t.id];
        if (!live) return t;
        return {
          ...t,
          latitude: live.latitude,
          longitude: live.longitude,
          speed: live.speed,
          status: statusFromSpeed(live.speed),
          lastUpdate: live.recordedAt,
        };
      }),
    [baseTrucks, locations],
  );

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: TRUCKS_KEY }),
    [queryClient],
  );

  const createMutation = useMutation({
    mutationFn: trucksApi.create,
    onSuccess: (truck) => {
      invalidate();
      toast({ title: 'Truck added', description: `${truck.name} has been added to your fleet.` });
    },
    onError: (err) => {
      toast({
        title: 'Failed to add truck',
        description: errorMessage(err, 'Try again.'),
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
        title: 'Update failed',
        description: errorMessage(err, 'Try again.'),
        variant: 'destructive',
      });
    },
  });

  const removeMutation = useMutation({
    mutationFn: trucksApi.remove,
    onSuccess: () => {
      invalidate();
      toast({ title: 'Truck deleted', description: 'The truck has been removed from your fleet.' });
    },
    onError: (err) => {
      toast({
        title: 'Failed to delete truck',
        description: errorMessage(err, 'Try again.'),
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
        },
      });
      toast({ title: 'Truck updated', description: 'Changes saved.' });
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
        title: current.isEnabled ? 'Truck disabled' : 'Truck enabled',
        description: `${current.name} has been ${current.isEnabled ? 'disabled' : 'enabled'}.`,
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
