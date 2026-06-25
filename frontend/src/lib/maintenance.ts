import { api } from '@/lib/api';

export interface FuelSummaryTruck {
  truck_id: string;
  truck_name: string;
  plate_number: string;
  gallons: number;
  cost: number;
  miles: number;
  mpg: number;
}

export interface FuelSummary {
  days: number;
  total_cost: number;
  total_gallons: number;
  total_miles: number;
  fleet_mpg: number;
  avg_price_per_gallon: number;
  trucks: FuelSummaryTruck[];
}

export interface BackendServiceInterval {
  id: string;
  truck_id: string;
  service_type: string;
  interval_km: number | null;
  interval_days: number | null;
  last_service_date: string | null;
  last_service_mileage: number | null;
  next_service_date: string | null;
  next_service_mileage: number | null;
  status: 'scheduled' | 'overdue' | 'completed';
}

export interface BackendMaintenanceRecord {
  id: string;
  truck_id: string;
  service_type: string;
  description: string | null;
  cost: number | null;
  mileage_at_service: number | null;
  performed_by: string | null;
  performed_at: string;
  notes: string | null;
  created_at: string;
}

export interface BackendFuelLog {
  id: string;
  truck_id: string;
  liters: number;          // gallons in demo
  cost_per_liter: number;  // $/gallon in demo
  total_cost: number;
  mileage_at_fill: number | null;
  fuel_station: string | null;
  filled_at: string;
  created_at: string;
}

export interface MaintenanceReminder {
  interval: BackendServiceInterval;
  truck: { id: string; name: string; plate_number: string } | null;
  due_soon: boolean;
}

export const maintenanceApi = {
  fuelSummary: (days = 30) =>
    api<FuelSummary>(`/api/maintenance/fuel-summary?days=${days}`),
  serviceIntervals: () =>
    api<BackendServiceInterval[]>('/api/service-intervals'),
  recentMaintenance: (limit = 50) =>
    api<BackendMaintenanceRecord[]>(`/api/maintenance/recent?limit=${limit}`),
  recentFuelLogs: (limit = 100) =>
    api<BackendFuelLog[]>(`/api/fuel-logs/recent?limit=${limit}`),
  reminders: () =>
    api<MaintenanceReminder[]>('/api/maintenance/reminders'),
};
