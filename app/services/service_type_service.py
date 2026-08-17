"""
Service-type service - CRUD for the ServiceType catalog.

Keeps all ServiceType table writes, validation and audit logic out of the
settings blueprint.
"""
from typing import Optional, Tuple

from app.models import Booking, ServiceType, db
from app.services.audit_service import AuditService

DURATION_UNITS = {'menit': 1, 'jam': 60, 'hari': 1440}
VALID_AFTER_SERVICE_VALUES = {'', 'Maintenance'}

# (message, error) - exactly one is non-None.
Result = Tuple[Optional[str], Optional[str]]


class ServiceTypeService:
    """Service for managing the ServiceType catalog."""

    @staticmethod
    def _duration_minutes(duration_value: str, duration_unit: str):
        duration_num = float(duration_value)
        return duration_num, duration_num * DURATION_UNITS.get(duration_unit, 1)

    @staticmethod
    def create(name: str, duration_value: str, duration_unit: str, after_service: str, actor_id: Optional[int]) -> Result:
        name = (name or '').strip()
        duration_unit = (duration_unit or 'menit').strip()
        after_service = (after_service or '').strip()
        try:
            duration_num, duration_minutes = ServiceTypeService._duration_minutes(duration_value, duration_unit)
        except (ValueError, TypeError):
            return None, 'Durasi harus berupa angka'
        if not name or len(name) < 3:
            return None, 'Nama layanan harus minimal 3 karakter'
        if after_service not in VALID_AFTER_SERVICE_VALUES:
            return None, 'After Service tidak valid'
        if ServiceType.query.filter_by(name=name).first():
            return None, 'Layanan dengan nama ini sudah ada'
        db.session.add(ServiceType(name=name, duration_minutes=duration_minutes, active=True, after_service=after_service or None))
        AuditService.log('service.create', actor_id=actor_id, details=f'name={name} duration={duration_num}{duration_unit} after_service={after_service or "-"}')
        db.session.commit()
        return f"Layanan '{name}' berhasil ditambahkan", None

    @staticmethod
    def update(service_id: int, name: str, duration_value: str, duration_unit: str, after_service: str, actor_id: Optional[int]) -> Result:
        name = (name or '').strip()
        duration_unit = (duration_unit or 'menit').strip()
        after_service = (after_service or '').strip()
        service = ServiceType.query.get(service_id)
        if not service:
            return None, 'Layanan tidak ditemukan'
        try:
            duration_num, duration_minutes = ServiceTypeService._duration_minutes(duration_value, duration_unit)
        except (ValueError, TypeError):
            return None, 'Durasi harus berupa angka'
        if not name or len(name) < 3:
            return None, 'Nama layanan harus minimal 3 karakter'
        if after_service not in VALID_AFTER_SERVICE_VALUES:
            return None, 'After Service tidak valid'
        if ServiceType.query.filter(ServiceType.name == name, ServiceType.id != service_id).first():
            return None, 'Layanan dengan nama ini sudah ada'
        service.name = name
        service.duration_minutes = duration_minutes
        service.after_service = after_service or None
        AuditService.log('service.update', actor_id=actor_id, details=f'service_id={service_id} name={name} duration={duration_num}{duration_unit} after_service={after_service or "-"}')
        db.session.commit()
        return f"Layanan '{name}' berhasil diperbarui", None

    @staticmethod
    def delete(service_id: int, actor_id: Optional[int]) -> Result:
        service = ServiceType.query.get(service_id)
        if not service:
            return None, 'Layanan tidak ditemukan'
        if Booking.query.filter_by(service_type_id=service_id).count() > 0:
            return None, 'Layanan tidak bisa dihapus karena masih digunakan di booking'
        service_name = service.name
        db.session.delete(service)
        AuditService.log('service.delete', actor_id=actor_id, details=f'service_id={service_id} name={service_name}')
        db.session.commit()
        return f"Layanan '{service_name}' berhasil dihapus", None

    @staticmethod
    def toggle(service_id: int, actor_id: Optional[int]) -> Result:
        service = ServiceType.query.get(service_id)
        if not service:
            return None, 'Layanan tidak ditemukan'
        service.active = not service.active
        AuditService.log('service.toggle', actor_id=actor_id, details=f'service_id={service_id} active={service.active}')
        db.session.commit()
        return f"Layanan '{service.name}' berhasil {'diaktifkan' if service.active else 'dinonaktifkan'}", None
