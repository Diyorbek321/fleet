/**
 * A run clears customs in the country it is going to. The form makes the
 * dispatcher say which way the run goes before a new trip is saved, and names
 * that country on the customs line, so the post typed there cannot be read as
 * the wrong side of the border.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import type { Trip } from '@/lib/trips';
import type { Truck } from '@/types';

import { TripFormDialog } from './TripFormDialog';

function renderForm(trip: Trip | null = null, trucks: Truck[] = []) {
  const onSubmit = vi.fn();
  renderWithProviders(
    <TripFormDialog
      open
      onOpenChange={() => {}}
      trip={trip}
      trucks={trucks}
      isPending={false}
      onSubmit={onSubmit}
    />,
  );
  return onSubmit;
}

const submit = () => fireEvent.click(screen.getByRole('button', { name: /save|saqlash|сохранить/i }));
const customsInput = () => document.getElementById('trip-customsPoint') as HTMLInputElement;
const customsLabel = () => document.querySelector('label[for="trip-customsPoint"]')?.textContent ?? '';

describe('TripFormDialog direction', () => {
  it('will not save a new trip until a direction is picked', () => {
    const onSubmit = renderForm();
    submit();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('names the destination country on the customs line and sends the direction', () => {
    const onSubmit = renderForm();
    const [uzRu, ruUz] = screen.getAllByRole('button', { pressed: false });

    fireEvent.click(uzRu);
    const russianLabel = customsLabel();
    fireEvent.click(ruUz);
    const uzbekLabel = customsLabel();
    expect(russianLabel).not.toEqual(uzbekLabel);

    fireEvent.change(customsInput(), { target: { value: 'Чукурсай' } });
    submit();
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ direction: 'ru_uz', customsPoint: 'Чукурсай' }),
    );
  });

  it('lets an old trip with no direction be edited and saved', () => {
    const onSubmit = renderForm({ id: 't-1', reference: 'TR-1', direction: null } as Trip);
    submit();
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ direction: null }));
  });
});

describe('TripFormDialog assignment', () => {
  it('asks for no driver and sends none: the server takes the truck\'s', () => {
    const truck = { id: 'tr-1', plateNumber: '01A111AA', driverName: 'Ali' } as Truck;
    const onSubmit = renderForm(
      { id: 't-1', reference: 'TR-1', direction: 'uz_ru', truckId: 'tr-1', driverId: 'd-old' } as Trip,
      [truck],
    );

    expect(screen.getByText('Ali')).toBeInTheDocument();
    submit();
    const input = onSubmit.mock.calls[0][0];
    expect(input).not.toHaveProperty('driverId');
    expect(input).not.toHaveProperty('isLoaded');
  });

  it('puts customs with the unloading, after the unloading address', () => {
    renderForm();
    const address = document.getElementById('trip-unloadingAddress')!;
    expect(address.compareDocumentPosition(customsInput()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('sends the customer who booked the truck', () => {
    const onSubmit = renderForm();
    fireEvent.click(screen.getAllByRole('button', { pressed: false })[0]);
    fireEvent.change(document.getElementById('trip-customer')!, { target: { value: 'Artel' } });
    submit();
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ customer: 'Artel' }));
  });
});
