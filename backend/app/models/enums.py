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
    """Who a user is inside the product.

    ``superadmin`` is the platform operator (us — the company selling FleetWatch
    to logistics firms), not a customer role. It is deliberately NOT a wildcard:
    a superadmin still belongs to exactly one organization (its own "Platform"
    org) and ``get_org_id`` keeps returning that org, so a superadmin sees no
    fleet data from customer tenants. Cross-company management happens only
    through ``/api/organizations/*``. Keeping it this way means every existing
    tenant-scoping test stays valid and the blast radius of the role is small.
    """
    superadmin = "superadmin"
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


class TripReportStatus(str, enum.Enum):
    """Lifecycle of a driver-filled trip expense report ("yo'l varaqasi")."""
    draft = "draft"
    submitted = "submitted"


class TripReportCountry(str, enum.Enum):
    """Which country's expense table a line item belongs to."""
    kz = "kz"
    ru = "ru"
    uz = "uz"


class TripReportExpenseCategory(str, enum.Enum):
    """Shared superset of expense categories across the KZ/RF/UZ tables.

    Not every category applies to every country — KZ/RF share one set,
    UZ has a partly different set — but the UI decides which categories to
    show per country, so one flat enum is enough here.
    """
    platon = "platon"
    food = "food"
    traffic_police = "traffic_police"  # ГАИ
    adblue = "adblue"
    fine = "fine"  # Штрафы
    spare_parts = "spare_parts"  # Запчасть
    repair = "repair"  # Ремонт
    refund = "refund"  # Возврат
    parking = "parking"  # Стоянка
    phone = "phone"  # Телефон
    transport = "transport"  # Транспорт
    shower = "shower"  # Душ
    groceries = "groceries"  # Продукты (UZ)
    parking_paperwork = "parking_paperwork"  # Оформления стоянка (UZ)
    taxi = "taxi"  # Такси (UZ)
    carwash = "carwash"  # Мойка (UZ)
