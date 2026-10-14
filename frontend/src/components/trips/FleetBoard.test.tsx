/**
 * The fleet board replaces the sheet the desk fills in by phone each morning,
 * so it is read the way that sheet is: a truck per row, the export and the
 * import each in their own column, dates as dd.mm.yyyy, and a blank — not
 * "06.01.1900" — where there is no trip.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { renderWithProviders } from '@/test/render';
import type { BoardRow, DispatchGroup, FleetBoard as Board } from '@/lib/fleetBoard';

vi.mock('@/lib/fleetBoard', () => ({
  fleetBoardApi: {
    get: vi.fn(),
    xlsx: vi.fn(),
    group: vi.fn(),
    linkGroup: vi.fn(),
    unlinkGroup: vi.fn(),
    sendNow: vi.fn(),
  },
}));

const { fleetBoardApi } = await import('@/lib/fleetBoard');
const { FleetBoard } = await import('./FleetBoard');

const exporting: BoardRow = {
  position: 1,
  truck_id: 't1',
  plate: '10 033 RBA/10 2462 BA',
  location: 'Актобе',
  location_at: '2026-10-14T03:00:00Z',
  export_trip: {
    trip_id: 'e1',
    reference: 'E-1',
    route: 'Ташкент - Мелеуз',
    loading_date: '2026-10-06',
    unloading_date: null,
    is_loaded: true,
    status: 'en_route',
  },
  import_trip: null,
};

const importing: BoardRow = {
  position: 2,
  truck_id: 't2',
  plate: '10 043 RBA/10 7914 AA',
  location: 'Шымкент',
  location_at: null,
  export_trip: null,
  import_trip: {
    trip_id: 'i1',
    reference: 'I-1',
    route: 'Чел - Ташкент',
    loading_date: '2026-10-15',
    unloading_date: '2026-10-21',
    is_loaded: true,
    status: 'planned',
  },
};

const idle: BoardRow = {
  position: 3,
  truck_id: 't3',
  plate: '10 088 PCA/10 4167 BA',
  location: null,
  location_at: null,
  export_trip: null,
  import_trip: null,
};

const board: Board = { day: '2026-10-14', rows: [exporting, importing, idle] };
const noGroup: DispatchGroup = {
  status: 'none',
  chat_title: null,
  activated_at: null,
  board_sent_on: null,
  deep_link: null,
};

function renderBoard() {
  return renderWithProviders(
    <MemoryRouter>
      <FleetBoard />
    </MemoryRouter>,
  );
}

function rowOf(plate: string): HTMLElement {
  return screen.getByText(plate).closest('tr') as HTMLElement;
}

describe('FleetBoard', () => {
  beforeEach(() => {
    vi.mocked(fleetBoardApi.get).mockResolvedValue(board);
    vi.mocked(fleetBoardApi.group).mockResolvedValue(noGroup);
  });

  it('puts the export and the import in their own columns', async () => {
    renderBoard();
    await screen.findByText(exporting.plate);

    const exportCells = within(rowOf(exporting.plate)).getAllByRole('cell');
    const importCells = within(rowOf(importing.plate)).getAllByRole('cell');

    // №, truck, place | export route, loading, unloading | import route, loading, unloading
    expect(exportCells[3]).toHaveTextContent('Ташкент - Мелеуз');
    expect(exportCells[4]).toHaveTextContent('06.10.2026');
    expect(exportCells[6]).toHaveTextContent('');
    expect(importCells[3]).toHaveTextContent('');
    expect(importCells[6]).toHaveTextContent('Чел - Ташкент');
    expect(importCells[8]).toHaveTextContent('21.10.2026');
  });

  it('never prints a placeholder date for a missing trip', async () => {
    renderBoard();
    await screen.findByText(idle.plate);

    expect(screen.queryByText(/1900/)).not.toBeInTheDocument();
  });

  it('narrows to the trucks carrying an import', async () => {
    renderBoard();
    await screen.findByText(exporting.plate);

    fireEvent.click(screen.getByRole('radio', { name: /On import/ }));

    expect(screen.getByText(importing.plate)).toBeInTheDocument();
    expect(screen.queryByText(exporting.plate)).not.toBeInTheDocument();
    expect(screen.queryByText(idle.plate)).not.toBeInTheDocument();
  });

  it('narrows to the trucks with nothing booked', async () => {
    renderBoard();
    await screen.findByText(exporting.plate);

    fireEvent.click(screen.getByRole('radio', { name: /Free/ }));

    expect(screen.getByText(idle.plate)).toBeInTheDocument();
    expect(screen.queryByText(importing.plate)).not.toBeInTheDocument();
  });

  it('finds a truck by its plate', async () => {
    renderBoard();
    await screen.findByText(exporting.plate);

    fireEvent.change(screen.getByPlaceholderText(/Search/), { target: { value: '7914' } });

    expect(screen.getByText(importing.plate)).toBeInTheDocument();
    expect(screen.queryByText(exporting.plate)).not.toBeInTheDocument();
  });
});
