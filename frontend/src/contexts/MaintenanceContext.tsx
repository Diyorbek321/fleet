import React, { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react';
import { addDays, isAfter, isBefore } from 'date-fns';
import type { ServiceInterval, MaintenanceRecord, FuelLog, FuelStats, ServiceType } from '@/types';
import { maintenanceApi, type BackendServiceInterval, type BackendMaintenanceRecord, type BackendFuelLog } from '@/lib/maintenance';
import { useAuth } from '@/contexts/AuthContext';

function mapServiceType(s: string): ServiceType {
  const allowed: ServiceType[] = ['oil_change', 'tire_rotation', 'brake_inspection', 'engine_service', 'transmission'];
  return (allowed.includes(s as ServiceType) ? s : 'other') as ServiceType;
}

const KM_TO_MILES = 0.621371;

function adaptInterval(b: BackendServiceInterval): ServiceInterval {
  const next = b.next_service_date ? new Date(b.next_service_date) : new Date();
  const last = b.last_service_date ? new Date(b.last_service_date) : new Date();
  return {
    id: b.id,
    truckId: b.truck_id,
    serviceType: mapServiceType(b.service_type),
    intervalMiles: b.interval_km ? Math.round(b.interval_km * KM_TO_MILES) : 0,
    intervalDays: b.interval_days ?? 0,
    lastServiceMiles: b.last_service_mileage ?? 0,
    lastServiceDate: last,
    nextServiceMiles: b.next_service_mileage ?? 0,
    nextServiceDate: next,
  };
}

function adaptRecord(b: BackendMaintenanceRecord): MaintenanceRecord {
  return {
    id: b.id,
    truckId: b.truck_id,
    serviceType: mapServiceType(b.service_type),
    date: new Date(b.performed_at),
    mileage: b.mileage_at_service ?? 0,
    cost: b.cost ?? 0,
    vendor: b.performed_by ?? undefined,
    notes: b.notes ?? undefined,
  };
}

function adaptFuelLog(b: BackendFuelLog): FuelLog {
  return {
    id: b.id,
    truckId: b.truck_id,
    date: new Date(b.filled_at),
    gallons: b.liters,
    pricePerGallon: b.cost_per_liter,
    totalCost: b.total_cost,
    mileage: b.mileage_at_fill ?? 0,
    location: b.fuel_station ?? undefined,
  };
}

interface MaintenanceContextType {
  serviceIntervals: ServiceInterval[];
  maintenanceRecords: MaintenanceRecord[];
  fuelLogs: FuelLog[];

  getUpcomingServices: (daysAhead?: number) => ServiceInterval[];
  getOverdueServices: () => ServiceInterval[];
  updateServiceInterval: (id: string, data: Partial<ServiceInterval>) => void;

  addMaintenanceRecord: (record: Omit<MaintenanceRecord, 'id'>) => void;
  getRecordsByTruck: (truckId: string) => MaintenanceRecord[];

  addFuelLog: (log: Omit<FuelLog, 'id'>) => void;
  getFuelLogsByTruck: (truckId: string) => FuelLog[];
  calculateFuelStats: (truckId?: string) => FuelStats;
}

const MaintenanceContext = createContext<MaintenanceContextType | undefined>(undefined);

const EMPTY_STATS: FuelStats = {
  totalGallons: 0,
  totalCost: 0,
  avgMpg: 0,
  avgPricePerGallon: 0,
};

export function MaintenanceProvider({ children }: { children: React.ReactNode }) {
  const [serviceIntervals, setServiceIntervals] = useState<ServiceInterval[]>([]);
  const [maintenanceRecords, setMaintenanceRecords] = useState<MaintenanceRecord[]>([]);
  const [fuelLogs, setFuelLogs] = useState<FuelLog[]>([]);
  const { isAuthenticated } = useAuth();

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    (async () => {
      try {
        const [intervals, records, logs] = await Promise.all([
          maintenanceApi.serviceIntervals(),
          maintenanceApi.recentMaintenance(200),
          maintenanceApi.recentFuelLogs(500),
        ]);
        if (cancelled) return;
        setServiceIntervals(intervals.map(adaptInterval));
        setMaintenanceRecords(records.map(adaptRecord));
        setFuelLogs(logs.map(adaptFuelLog));
      } catch {
        /* leave state empty if API not reachable */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  const getUpcomingServices = useCallback(
    (daysAhead = 14): ServiceInterval[] => {
      const now = new Date();
      const futureDate = addDays(now, daysAhead);
      return serviceIntervals
        .filter((interval) => {
          const nextDate = new Date(interval.nextServiceDate);
          return isAfter(nextDate, now) && isBefore(nextDate, futureDate);
        })
        .sort(
          (a, b) => new Date(a.nextServiceDate).getTime() - new Date(b.nextServiceDate).getTime(),
        );
    },
    [serviceIntervals],
  );

  const getOverdueServices = useCallback((): ServiceInterval[] => {
    const now = new Date();
    return serviceIntervals
      .filter((interval) => isBefore(new Date(interval.nextServiceDate), now))
      .sort(
        (a, b) => new Date(a.nextServiceDate).getTime() - new Date(b.nextServiceDate).getTime(),
      );
  }, [serviceIntervals]);

  const updateServiceInterval = useCallback((id: string, data: Partial<ServiceInterval>) => {
    setServiceIntervals((prev) =>
      prev.map((interval) => (interval.id === id ? { ...interval, ...data } : interval)),
    );
  }, []);

  const addMaintenanceRecord = useCallback(
    (record: Omit<MaintenanceRecord, 'id'>) => {
      const newRecord: MaintenanceRecord = { ...record, id: `MR-${Date.now()}` };
      setMaintenanceRecords((prev) => [newRecord, ...prev]);

      const interval = serviceIntervals.find(
        (si) => si.truckId === record.truckId && si.serviceType === record.serviceType,
      );
      if (interval) {
        updateServiceInterval(interval.id, {
          lastServiceDate: record.date,
          lastServiceMiles: record.mileage,
          nextServiceDate: addDays(record.date, interval.intervalDays),
          nextServiceMiles: record.mileage + interval.intervalMiles,
        });
      }
    },
    [serviceIntervals, updateServiceInterval],
  );

  const getRecordsByTruck = useCallback(
    (truckId: string): MaintenanceRecord[] =>
      maintenanceRecords
        .filter((r) => r.truckId === truckId)
        .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()),
    [maintenanceRecords],
  );

  const addFuelLog = useCallback((log: Omit<FuelLog, 'id'>) => {
    const newLog: FuelLog = { ...log, id: `FL-${Date.now()}` };
    setFuelLogs((prev) =>
      [newLog, ...prev].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()),
    );
  }, []);

  const getFuelLogsByTruck = useCallback(
    (truckId: string): FuelLog[] =>
      fuelLogs
        .filter((l) => l.truckId === truckId)
        .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()),
    [fuelLogs],
  );

  const calculateFuelStats = useCallback(
    (truckId?: string): FuelStats => {
      const logs = truckId ? fuelLogs.filter((l) => l.truckId === truckId) : fuelLogs;
      if (logs.length < 2) return EMPTY_STATS;

      const totalGallons = logs.reduce((sum, l) => sum + l.gallons, 0);
      const totalCost = logs.reduce((sum, l) => sum + l.totalCost, 0);
      const avgPricePerGallon = totalCost / totalGallons;

      const sortedLogs = [...logs].sort((a, b) => a.mileage - b.mileage);
      let totalMiles = 0;
      let totalGallonsForMpg = 0;
      for (let i = 1; i < sortedLogs.length; i++) {
        const milesDriven = sortedLogs[i].mileage - sortedLogs[i - 1].mileage;
        if (milesDriven > 0 && milesDriven < 1000) {
          totalMiles += milesDriven;
          totalGallonsForMpg += sortedLogs[i].gallons;
        }
      }
      const avgMpg = totalGallonsForMpg > 0 ? totalMiles / totalGallonsForMpg : 0;

      return {
        totalGallons: Math.round(totalGallons * 10) / 10,
        totalCost: Math.round(totalCost * 100) / 100,
        avgMpg: Math.round(avgMpg * 10) / 10,
        avgPricePerGallon: Math.round(avgPricePerGallon * 100) / 100,
      };
    },
    [fuelLogs],
  );

  const value = useMemo<MaintenanceContextType>(
    () => ({
      serviceIntervals,
      maintenanceRecords,
      fuelLogs,
      getUpcomingServices,
      getOverdueServices,
      updateServiceInterval,
      addMaintenanceRecord,
      getRecordsByTruck,
      addFuelLog,
      getFuelLogsByTruck,
      calculateFuelStats,
    }),
    [
      serviceIntervals,
      maintenanceRecords,
      fuelLogs,
      getUpcomingServices,
      getOverdueServices,
      updateServiceInterval,
      addMaintenanceRecord,
      getRecordsByTruck,
      addFuelLog,
      getFuelLogsByTruck,
      calculateFuelStats,
    ],
  );

  return <MaintenanceContext.Provider value={value}>{children}</MaintenanceContext.Provider>;
}

export function useMaintenance(): MaintenanceContextType {
  const ctx = useContext(MaintenanceContext);
  if (!ctx) throw new Error('useMaintenance must be used within MaintenanceProvider');
  return ctx;
}
