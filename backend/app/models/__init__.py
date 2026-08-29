from app.models.organizations import Organization  # noqa
from app.models.trucks import Truck, TruckLocation, TruckLocationHistory  # noqa
from app.models.drivers import Driver, DriverAssignment, SafetyScore  # noqa
from app.models.maintenance import ServiceInterval, MaintenanceRecord, FuelLog  # noqa
from app.models.users import User  # noqa
from app.models.driver_app import Shift, MaintenanceRequest, PushToken, QueueWatch, DriverExpense  # noqa
from app.models.geofences import Geofence, GeofenceEvent  # noqa
from app.models.trips import Trip, TripEvent, TripSegment, TripDocument  # noqa
from app.models.notifications import TripSubscription  # noqa
from app.models.trip_reports import TripExpenseReport, TripFuelRow, TripCountryExpenseLine  # noqa
# Imported here even though nothing else in this package needs it: `alembic/env.py`
# builds `target_metadata` from `import app.models` alone, so a model that only the
# routers import is absent from the metadata and `--autogenerate` emits a
# `op.drop_table('devices')` into the next migration — which would wipe every GPS
# tracker's imei + api_key_hash. See tests/test_schema_drift.py.
from app.models.devices import Device  # noqa
