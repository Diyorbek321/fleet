import { api, ApiError, tokenStorage } from '@/lib/api';

export type ReportType = 'fuel' | 'maintenance' | 'trucks' | 'drivers' | 'full';
export type ReportLanguage = 'en' | 'ru' | 'uz';

export interface GeneratedReportFile {
  filename: string;
  blob: Blob;
}

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export interface FleetSummary {
  totalTrucks: number;
  activeDrivers: number;
  totalMaintenanceCost: number;
  totalFuelCost: number;
  totalFuelLiters: number;
  distanceKm: number;
  windowStart: Date;
  windowEnd: Date;
}

export interface TruckDistance {
  truckId: string;
  truckName: string;
  plateNumber: string;
  distanceKm: number;
  pointCount: number;
}

export type ExpenseCategory =
  | 'food'
  | 'toll'
  | 'parking'
  | 'fine'
  | 'repair'
  | 'lodging'
  | 'customs'
  | 'other';

export interface DriverExpenseRank {
  driverId: string;
  driverName: string;
  total: number;
  entryCount: number;
  byCategory: Partial<Record<ExpenseCategory, number>>;
}

interface BackendDriverExpenseRank {
  driver_id: string;
  driver_name: string;
  total: number;
  entry_count: number;
  by_category: Partial<Record<ExpenseCategory, number>>;
}

interface BackendFleetSummary {
  total_trucks: number;
  active_drivers: number;
  total_maintenance_cost: number;
  total_fuel_cost: number;
  total_fuel_liters: number;
  distance_km: number;
  window_start: string;
  window_end: string;
}

interface BackendTruckDistance {
  truck_id: string;
  truck_name: string;
  plate_number: string;
  distance_km: number;
  point_count: number;
}

export const reportsApi = {
  fleetSummary: async (days: number): Promise<FleetSummary> => {
    const data = await api<BackendFleetSummary>(`/api/reports/fleet-summary?days=${days}`);
    return {
      totalTrucks: data.total_trucks,
      activeDrivers: data.active_drivers,
      totalMaintenanceCost: data.total_maintenance_cost,
      totalFuelCost: data.total_fuel_cost,
      totalFuelLiters: data.total_fuel_liters,
      distanceKm: data.distance_km,
      windowStart: new Date(data.window_start),
      windowEnd: new Date(data.window_end),
    };
  },
  generate: async (
    reportType: ReportType,
    language: ReportLanguage,
    days: number,
  ): Promise<GeneratedReportFile> => {
    const token = tokenStorage.getAccess();
    const params = new URLSearchParams({
      report_type: reportType,
      language,
      days: String(days),
    });
    const res = await fetch(`${BASE_URL}/api/reports/generate?${params.toString()}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const err = await res.json();
        detail = err.detail ?? detail;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, detail);
    }
    const disposition = res.headers.get('Content-Disposition') ?? '';
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match?.[1] ?? `fleet-${reportType}-${language}.md`;
    const blob = await res.blob();
    return { filename, blob };
  },
  driverExpenses: async (days: number): Promise<DriverExpenseRank[]> => {
    const data = await api<BackendDriverExpenseRank[]>(`/api/reports/driver-expenses?days=${days}`);
    return data.map((d) => ({
      driverId: d.driver_id,
      driverName: d.driver_name,
      total: d.total,
      entryCount: d.entry_count,
      byCategory: d.by_category ?? {},
    }));
  },
  truckDistances: async (days: number): Promise<TruckDistance[]> => {
    const data = await api<BackendTruckDistance[]>(`/api/reports/truck-distances?days=${days}`);
    return data.map((t) => ({
      truckId: t.truck_id,
      truckName: t.truck_name,
      plateNumber: t.plate_number,
      distanceKm: t.distance_km,
      pointCount: t.point_count,
    }));
  },
};
