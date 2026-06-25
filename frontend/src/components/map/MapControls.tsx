import React from 'react';
import { Search, Focus, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Truck } from '@/types';
import { useTrucks } from '@/contexts/TruckContext';

interface MapControlsProps {
  trucks: Truck[];
}

export function MapControls({ trucks }: MapControlsProps) {
  const { setSelectedTruck, refreshTrucks } = useTrucks();

  const handleTruckSelect = (truckId: string) => {
    const truck = trucks.find((t) => t.id === truckId);
    if (truck) {
      setSelectedTruck(truck);
    }
  };

  return (
    <div className="absolute top-4 left-4 z-10 flex flex-col gap-2">
      <div className="flex gap-2">
        <Select onValueChange={handleTruckSelect}>
          <SelectTrigger className="w-48 bg-card border-border shadow-card">
            <Focus className="mr-2 h-4 w-4" />
            <SelectValue placeholder="Jump to truck" />
          </SelectTrigger>
          <SelectContent className="bg-popover">
            {trucks
              .filter((t) => t.isEnabled)
              .map((truck) => (
                <SelectItem key={truck.id} value={truck.id}>
                  {truck.plateNumber}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>

        <Button
          variant="secondary"
          size="icon"
          onClick={() => refreshTrucks()}
          className="bg-card border border-border shadow-card hover:bg-secondary"
        >
          <RotateCcw className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
