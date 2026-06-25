import { api } from '@/lib/api';

export interface LeakageSummary {
  windowDays: number;
  estimatedFuelWasteCost: number;
  flaggedTrucks: number;
  fuelBaselineLPer100km: number;
  unauthorizedStopCount: number;
  totalIdleHours: number;
  activeTrips: number;
  deliveredTrips: number;
}

export interface FuelAnomalyRow {
  truckId: string;
  truckName: string;
  plateNumber: string;
  distanceKm: number;
  liters: number;
  lPer100km: number;
  baselineLPer100km: number;
  flagged: boolean;
  estimatedWasteCost: number;
}

export interface UnauthorizedStop {
  truckId: string;
  truckName: string;
  plateNumber: string;
  latitude: number;
  longitude: number;
  startedAt: string;
  endedAt: string;
  durationMinutes: number;
}

export const analyticsApi = {
  leakageSummary: async (days = 30): Promise<LeakageSummary> => {
    const d = await api<{
      window_days: number;
      estimated_fuel_waste_cost: number;
      flagged_trucks: number;
      fuel_baseline_l_per_100km: number;
      unauthorized_stop_count: number;
      total_idle_hours: number;
      active_trips: number;
      delivered_trips: number;
    }>(`/api/analytics/leakage-summary?days=${days}`);
    return {
      windowDays: d.window_days,
      estimatedFuelWasteCost: d.estimated_fuel_waste_cost,
      flaggedTrucks: d.flagged_trucks,
      fuelBaselineLPer100km: d.fuel_baseline_l_per_100km,
      unauthorizedStopCount: d.unauthorized_stop_count,
      totalIdleHours: d.total_idle_hours,
      activeTrips: d.active_trips,
      deliveredTrips: d.delivered_trips,
    };
  },
  fuelAnomalies: async (days = 30): Promise<FuelAnomalyRow[]> => {
    const d = await api<{
      trucks: Array<{
        truck_id: string;
        truck_name: string;
        plate_number: string;
        distance_km: number;
        liters: number;
        l_per_100km: number;
        baseline_l_per_100km: number;
        flagged: boolean;
        estimated_waste_cost: number;
      }>;
    }>(`/api/analytics/fuel-anomalies?days=${days}`);
    return d.trucks.map((r) => ({
      truckId: r.truck_id,
      truckName: r.truck_name,
      plateNumber: r.plate_number,
      distanceKm: r.distance_km,
      liters: r.liters,
      lPer100km: r.l_per_100km,
      baselineLPer100km: r.baseline_l_per_100km,
      flagged: r.flagged,
      estimatedWasteCost: r.estimated_waste_cost,
    }));
  },
  unauthorizedStops: async (days = 30): Promise<UnauthorizedStop[]> => {
    const d = await api<{
      stops: Array<{
        truck_id: string;
        truck_name: string;
        plate_number: string;
        latitude: number;
        longitude: number;
        started_at: string;
        ended_at: string;
        duration_minutes: number;
      }>;
    }>(`/api/analytics/unauthorized-stops?days=${days}`);
    return d.stops.map((s) => ({
      truckId: s.truck_id,
      truckName: s.truck_name,
      plateNumber: s.plate_number,
      latitude: s.latitude,
      longitude: s.longitude,
      startedAt: s.started_at,
      endedAt: s.ended_at,
      durationMinutes: s.duration_minutes,
    }));
  },
};
