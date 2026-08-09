"""Pytest configuration and fixtures for the app."""

import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

from app.models import db, User, Customer, ServiceType, Booking, WhatsAppMessage, ReminderLog, MaintenanceReminder, AuditLog, AppSetting
from app.app import create_app


@pytest.fixture
def app():
    """Create a Flask app configured for testing."""
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    
    # Temporarily replace bootstrap_defaults to be a no-op for testing
    from app import app as app_module
    original_bootstrap = app_module.bootstrap_defaults
    
    def mock_bootstrap():
        # Just create default service types, don't create users
        _create_test_service_types()
    
    app_module.bootstrap_defaults = mock_bootstrap
    
    try:
        from app.app import create_app
        test_app = create_app()
        test_app.config["TESTING"] = True
        test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        test_app.config["WTF_CSRF_ENABLED"] = False
        
        with test_app.app_context():
            db.drop_all()  # Drop any existing tables
            db.create_all()  # Create fresh tables
            _create_test_service_types()
            
        yield test_app
        
        with test_app.app_context():
            db.session.remove()
            db.drop_all()
    finally:
        # Restore original bootstrap_defaults
        app_module.bootstrap_defaults = original_bootstrap


def _create_test_service_types():
    """Create default service types for tests."""
    defaults = [
        ("Interior Detailing", 480, None),
        ("Polishing", 480, None),
        ("PPF", 7200, "Maintenance"),
        ("Coating Premium", 4320, "Maintenance"),
        ("Glass Polishing", 120, None),
        ("Cuci Mobil", 15, None),
        ("Lainnya", 120, None),
    ]
    for name, duration, after_service in defaults:
        existing = ServiceType.query.filter_by(name=name).first()
        if not existing:
            db.session.add(ServiceType(name=name, duration_minutes=duration, after_service=after_service))
    db.session.commit()


@pytest.fixture
def client(app):
    """Test client for the Flask app."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI runner for the Flask app."""
    return app.test_cli_runner()


@pytest.fixture
def app_context(app):
    """Application context for manual testing."""
    with app.app_context():
        yield app


@pytest.fixture
def user(app):
    """Create a test admin user."""
    with app.app_context():
        user = User(
            username="testuser",
            role="admin",
            active=True,
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    
    def get_user():
        return db.session.get(User, user_id)
    
    return get_user()


@pytest.fixture
def cs_user(app):
    """Create a test customer service user."""
    with app.app_context():
        user = User(
            username="testcs",
            role="cs",
            active=True,
        )
        user.set_password("cs_pass")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    
    def get_user():
        return db.session.get(User, user_id)
    
    return get_user()


@pytest.fixture
def tech_user(app):
    """Create a test technician user."""
    with app.app_context():
        user = User(
            username="testtech",
            role="technician",
            active=True,
        )
        user.set_password("tech_pass")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    
    def get_user():
        return db.session.get(User, user_id)
    
    return get_user()


@pytest.fixture
def customer(app):
    """Create a test customer."""
    with app.app_context():
        customer = Customer(
            name="John Doe",
            phone="6281234567890",
            vehicle_info="Toyota Rush GR",
            notes="Regular customer",
        )
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id
    
    # Return a callable that fetches the customer in the test context
    def get_customer():
        return db.session.get(Customer, customer_id)
    
    return get_customer()


@pytest.fixture
def customer_with_lid(app):
    """Create a test customer with LID."""
    with app.app_context():
        customer = Customer(
            name="Jane Smith",
            phone="6281234567891",
            lid="123456789012345",
            vehicle_info="Honda City",
            notes="WhatsApp via LID",
        )
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id
    
    def get_customer():
        return db.session.get(Customer, customer_id)
    
    return get_customer()


@pytest.fixture
def service_type(app):
    """Create a test service type."""
    with app.app_context():
        # Check if it already exists (from bootstrap)
        service = ServiceType.query.filter_by(name="Coating Premium").first()
        if service is None:
            service = ServiceType(
                name="Coating Premium",
                duration_minutes=360,
                active=True,
            )
            db.session.add(service)
            db.session.commit()
        service_id = service.id
    
    def get_service():
        return db.session.get(ServiceType, service_id)
    
    return get_service()


@pytest.fixture
def service_ppf(app):
    """Create a PPF service type."""
    with app.app_context():
        # Check if it already exists (from bootstrap)
        service = ServiceType.query.filter_by(name="PPF").first()
        if service is None:
            service = ServiceType(
                name="PPF",
                duration_minutes=480,
                active=True,
            )
            db.session.add(service)
            db.session.commit()
        service_id = service.id
    
    def get_service():
        return db.session.get(ServiceType, service_id)
    
    return get_service()


@pytest.fixture
def booking(app):
    """Create a test booking."""
    with app.app_context():
        # Create customer
        customer = Customer(
            name="John Doe",
            phone="6281234567890",
            vehicle_info="Toyota Rush GR",
        )
        db.session.add(customer)
        db.session.flush()
        
        # Create service
        service = ServiceType.query.filter_by(name="Coating Premium").first()
        if not service:
            service = ServiceType(name="Coating Premium", duration_minutes=360)
            db.session.add(service)
            db.session.flush()
        
        start_time = datetime.now(ZoneInfo("Asia/Jakarta")).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        end_time = start_time + timedelta(minutes=service.duration_minutes)
        
        booking = Booking(
            customer_id=customer.id,
            service_type_id=service.id,
            scheduled_start=start_time,
            scheduled_end=end_time,
            status="dikonfirmasi",
            source="manual",
            vehicle_type="Toyota Rush GR",
            license_plate="B1234XYZ",
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id
    
    def get_booking():
        return db.session.get(Booking, booking_id)
    
    return get_booking()


@pytest.fixture
def session_login(client, app):
    """Fixture that logs in a user via session."""
    with app.app_context():
        user = User.query.filter_by(username="test_admin").first()
        if not user:
            user = User(username="test_admin", role="admin", active=True)
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
        
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["role"] = user.role
    return client


@pytest.fixture
def session_login_cs(client, app):
    """Fixture that logs in a CS user via session."""
    with app.app_context():
        user = User.query.filter_by(username="test_cs").first()
        if not user:
            user = User(username="test_cs", role="cs", active=True)
            user.set_password("cs_pass")
            db.session.add(user)
            db.session.commit()
        
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["role"] = user.role
    return client


def get_jakarta_time(hour=10, minute=0):
    """Helper to get a time in Jakarta timezone."""
    return datetime.now(ZoneInfo("Asia/Jakarta")).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
