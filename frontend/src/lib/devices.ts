import { api } from '@/lib/api';

export interface Device {
  id: string;
  imei: string;
  name: string | null;
  truckId: string | null;
  lastSeenAt: Date | null;
  createdAt: Date;
}

export interface DeviceCreated extends Device {
  apiKey: string;
}

interface BackendDevice {
  id: string;
  imei: string;
  name: string | null;
  truck_id: string | null;
  last_seen_at: string | null;
  created_at: string;
}

interface BackendDeviceCreated extends BackendDevice {
  api_key: string;
}

function adapt(d: BackendDevice): Device {
  return {
    id: d.id,
    imei: d.imei,
    name: d.name,
    truckId: d.truck_id,
    lastSeenAt: d.last_seen_at ? new Date(d.last_seen_at) : null,
    createdAt: new Date(d.created_at),
  };
}

export const devicesApi = {
  list: async (): Promise<Device[]> => {
    const data = await api<BackendDevice[]>('/api/devices');
    return data.map(adapt);
  },
  enroll: async (input: {
    imei: string;
    name?: string;
    truckId?: string;
  }): Promise<DeviceCreated> => {
    const data = await api<BackendDeviceCreated>('/api/devices', {
      method: 'POST',
      body: {
        imei: input.imei,
        name: input.name,
        truck_id: input.truckId,
      },
    });
    return { ...adapt(data), apiKey: data.api_key };
  },
  rotateKey: async (id: string): Promise<{ apiKey: string }> => {
    const data = await api<{ api_key: string }>(`/api/devices/${id}/rotate-key`, {
      method: 'POST',
      body: {},
    });
    return { apiKey: data.api_key };
  },
  update: async (
    id: string,
    patch: { name?: string; truckId?: string | null },
  ): Promise<Device> => {
    const body: Record<string, unknown> = {};
    if (patch.name !== undefined) body.name = patch.name;
    if (patch.truckId !== undefined) body.truck_id = patch.truckId;
    const data = await api<BackendDevice>(`/api/devices/${id}`, { method: 'PUT', body });
    return adapt(data);
  },
  remove: async (id: string): Promise<void> => {
    await api<void>(`/api/devices/${id}`, { method: 'DELETE' });
  },
};
