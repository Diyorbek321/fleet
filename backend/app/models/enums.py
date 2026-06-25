import enum

class TruckStatus(str, enum.Enum):
    moving = "moving"
    stopped = "stopped"
    idle = "idle"
    offline = "offline"
    maintenance = "maintenance"

class DriverStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    on_leave = "on_leave"

class ServiceType(str, enum.Enum):
    oil_change = "oil_change"
    tire_rotation = "tire_rotation"
    brake_inspection = "brake_inspection"
    engine_service = "engine_service"
    transmission = "transmission"
    general = "general"

class ServiceStatus(str, enum.Enum):
    scheduled = "scheduled"
    overdue = "overdue"
    completed = "completed"

class UserRole(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    operator = "operator"
    driver = "driver"


class ShiftStatus(str, enum.Enum):
    active = "active"
    ended = "ended"


class MaintenanceRequestStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class GeofenceEventType(str, enum.Enum):
    enter = "enter"
    exit = "exit"


class TripStatus(str, enum.Enum):
    """Lifecycle of a freight trip/order.

    The unit of work that actually earns money: a load moving from shipper to
    consignee. Fuel, expenses and geofence dwell all hang off this so the owner
    can see profit-per-trip and where money leaks.
    """
    draft = "draft"
    planned = "planned"
    loading = "loading"
    en_route = "en_route"
    at_border = "at_border"
    delivered = "delivered"
    cancelled = "cancelled"


class TripEventType(str, enum.Enum):
    """A logged milestone in a trip's timeline."""
    created = "created"
    status_change = "status_change"
    note = "note"
    border_arrival = "border_arrival"
    border_clear = "border_clear"
    pod = "pod"  # proof of delivery


class SegmentKind(str, enum.Enum):
    """Whether a trip segment is the truck moving or stopped/idling."""
    moving = "moving"
    stopped = "stopped"


class ExpenseCategory(str, enum.Enum):
    """Categories for driver-reported daily expenses (fuel is tracked separately)."""
    food = "food"
    toll = "toll"
    parking = "parking"
    fine = "fine"
    repair = "repair"
    lodging = "lodging"
    customs = "customs"
    other = "other"
