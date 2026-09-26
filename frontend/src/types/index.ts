export type TruckStatus = 'moving' | 'stopped' | 'offline';

export type TrailerVolume = 'standart' | 'mega';

export interface Truck {
  id: string;
  plateNumber: string;
  name: string;
  model?: string;
  /** Make of the tractor unit, e.g. "MAN". */
  tractorBrand?: string;
  /** Make of the semi-trailer, e.g. "Schmitz". Separate because it is a
   *  separate vehicle: bought, serviced and replaced on its own. */
  trailerBrand?: string;
  /** Capacity class of the trailer — what a load is booked against. */
  trailerVolume?: TrailerVolume;
  driverName?: string;
  /** ISO date the insurance policy runs out, if known. */
  insuranceExpiry?: string | null;
  status: TruckStatus;
  speed: number;
  latitude: number;
  longitude: number;
  /** Human-readable place for the coordinates above, when known. */
  address?: string | null;
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
