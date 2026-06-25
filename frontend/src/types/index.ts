export type TruckStatus = 'moving' | 'stopped' | 'offline';

export interface Truck {
  id: string;
  plateNumber: string;
  name: string;
  deviceImei: string;
  model?: string;
  driverName?: string;
  status: TruckStatus;
  speed: number;
  latitude: number;
  longitude: number;
  lastUpdate: Date;
  isEnabled: boolean;
}

export interface TruckLocation {
  truckId: string;
  latitude: number;
  longitude: number;
  speed: number;
  heading: number;
  timestamp: Date;
}

export interface User {
  id: string;
  email: string;
  name: string;
  avatar?: string;
}

export interface Notification {
  id: string;
  title: string;
  message: string;
  type: 'info' | 'warning' | 'error' | 'success';
  timestamp: Date;
  read: boolean;
}

export interface DashboardStats {
  totalTrucks: number;
  movingTrucks: number;
  stoppedTrucks: number;
  offlineTrucks: number;
}

// Maintenance & Service Types
export type ServiceType = 'oil_change' | 'tire_rotation' | 'brake_inspection' | 'engine_service' | 'transmission' | 'other';

export interface ServiceInterval {
  id: string;
  truckId: string;
  serviceType: ServiceType;
  intervalMiles: number;
  intervalDays: number;
  lastServiceMiles: number;
  lastServiceDate: Date;
  nextServiceMiles: number;
  nextServiceDate: Date;
  notes?: string;
}

export interface MaintenanceRecord {
  id: string;
  truckId: string;
  serviceType: ServiceType;
  date: Date;
  mileage: number;
  cost: number;
  vendor?: string;
  notes?: string;
}

export interface FuelLog {
  id: string;
  truckId: string;
  date: Date;
  gallons: number;
  pricePerGallon: number;
  totalCost: number;
  mileage: number;
  location?: string;
}

export interface FuelStats {
  totalGallons: number;
  totalCost: number;
  avgMpg: number;
  avgPricePerGallon: number;
}
