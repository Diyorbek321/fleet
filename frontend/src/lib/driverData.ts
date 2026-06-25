import { api } from '@/lib/api';

// ---- Maintenance requests (driver-submitted issue reports) ----

export type MaintenanceRequestStatus = 'open' | 'acknowledged' | 'resolved';

export interface MaintenanceRequest {
  id: string;
  driverId: string | null;
  driverName: string | null;
  truckId: string | null;
  truckPlate: string | null;
  title: string;
  description: string | null;
  photoUrl: string | null;
  status: MaintenanceRequestStatus;
  createdAt: string;
}

interface BackendMaintenanceRequest {
  id: string;
  driver_id: string | null;
  driver_name: string | null;
  truck_id: string | null;
  truck_plate: string | null;
  title: string;
  description: string | null;
  photo_url: string | null;
  status: MaintenanceRequestStatus;
  created_at: string;
}

function adaptRequest(r: BackendMaintenanceRequest): MaintenanceRequest {
  return {
    id: r.id,
    driverId: r.driver_id,
    driverName: r.driver_name,
    truckId: r.truck_id,
    truckPlate: r.truck_plate,
    title: r.title,
    description: r.description,
    photoUrl: r.photo_url,
    status: r.status,
    createdAt: r.created_at,
  };
}

// ---- Driver expenses (individual line items) ----

export type ExpenseCategory =
  | 'food' | 'toll' | 'parking' | 'fine' | 'repair' | 'lodging' | 'customs' | 'other';

export interface DriverExpense {
  id: string;
  truckPlate: string | null;
  category: ExpenseCategory;
  amount: number;
  note: string | null;
  receiptUrl: string | null;
  spentAt: string;
}

interface BackendExpense {
  id: string;
  truck_plate: string | null;
  category: ExpenseCategory;
  amount: number;
  note: string | null;
  receipt_url: string | null;
  spent_at: string;
}

// ---- Shifts ----

export interface DriverShift {
  id: string;
  truckPlate: string | null;
  status: 'active' | 'ended';
  startedAt: string;
  endedAt: string | null;
  startMileage: number | null;
  endMileage: number | null;
}

interface BackendShift {
  id: string;
  truck_plate: string | null;
  status: 'active' | 'ended';
  started_at: string;
  ended_at: string | null;
  start_mileage: number | null;
  end_mileage: number | null;
}

export const driverDataApi = {
  maintenanceRequests: async (status?: MaintenanceRequestStatus): Promise<MaintenanceRequest[]> => {
    const data = await api<BackendMaintenanceRequest[]>(
      `/api/maintenance-requests${status ? `?status=${status}` : ''}`,
    );
    return data.map(adaptRequest);
  },
  updateRequestStatus: async (
    id: string,
    status: MaintenanceRequestStatus,
  ): Promise<MaintenanceRequest> => {
    const data = await api<BackendMaintenanceRequest>(
      `/api/maintenance-requests/${id}/status`,
      { method: 'PUT', body: { status } },
    );
    return adaptRequest(data);
  },
  expenses: async (driverId: string): Promise<DriverExpense[]> => {
    const data = await api<BackendExpense[]>(`/api/drivers/${driverId}/expenses`);
    return data.map((e) => ({
      id: e.id,
      truckPlate: e.truck_plate,
      category: e.category,
      amount: e.amount,
      note: e.note,
      receiptUrl: e.receipt_url,
      spentAt: e.spent_at,
    }));
  },
  shifts: async (driverId: string): Promise<DriverShift[]> => {
    const data = await api<BackendShift[]>(`/api/drivers/${driverId}/shifts`);
    return data.map((s) => ({
      id: s.id,
      truckPlate: s.truck_plate,
      status: s.status,
      startedAt: s.started_at,
      endedAt: s.ended_at,
      startMileage: s.start_mileage,
      endMileage: s.end_mileage,
    }));
  },
};
