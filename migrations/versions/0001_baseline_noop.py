"""baseline schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-10 00:00:00

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''
    CREATE TABLE IF NOT EXISTS "user" (
        id SERIAL PRIMARY KEY,
        username VARCHAR(80) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(20) NOT NULL,
        active BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    op.execute('''
    CREATE TABLE IF NOT EXISTS customer (
        id SERIAL PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        phone VARCHAR(30) NOT NULL UNIQUE,
        lid VARCHAR(40),
        vehicle_info VARCHAR(200),
        notes TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_customer_lid ON customer (lid)')

    op.execute('''
    CREATE TABLE IF NOT EXISTS service_type (
        id SERIAL PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        duration_minutes INTEGER NOT NULL,
        active BOOLEAN NOT NULL DEFAULT true,
        after_service VARCHAR(50),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    op.execute('''
    CREATE TABLE IF NOT EXISTS booking (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customer(id),
        service_type_id INTEGER NOT NULL REFERENCES service_type(id),
        scheduled_start TIMESTAMP NOT NULL,
        scheduled_end TIMESTAMP NOT NULL,
        price_amount NUMERIC(12,2),
        status VARCHAR(30) NOT NULL DEFAULT 'confirmed',
        source VARCHAR(30) NOT NULL DEFAULT 'manual',
        notes TEXT,
        other_info VARCHAR(255),
        vehicle_type VARCHAR(100),
        license_plate VARCHAR(20),
        created_by_user_id INTEGER REFERENCES "user"(id),
        assigned_tech_id INTEGER REFERENCES "user"(id),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    op.execute('''
    CREATE TABLE IF NOT EXISTS whats_app_message (
        id SERIAL PRIMARY KEY,
        direction VARCHAR(10) NOT NULL,
        phone VARCHAR(30) NOT NULL,
        message_text TEXT NOT NULL,
        payload_json TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'received',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    op.execute('''
    CREATE TABLE IF NOT EXISTS reminder_log (
        id SERIAL PRIMARY KEY,
        booking_id INTEGER NOT NULL REFERENCES booking(id),
        reminder_type VARCHAR(20) NOT NULL,
        scheduled_for TIMESTAMP NOT NULL,
        sent_at TIMESTAMP,
        status VARCHAR(20) NOT NULL DEFAULT 'queued',
        error_message VARCHAR(200)
    )
    ''')

    op.execute('''
    CREATE TABLE IF NOT EXISTS maintenance_reminder (
        id SERIAL PRIMARY KEY,
        booking_id INTEGER NOT NULL UNIQUE REFERENCES booking(id),
        customer_id INTEGER NOT NULL REFERENCES customer(id),
        service_type VARCHAR(50) NOT NULL,
        completed_at TIMESTAMP NOT NULL,
        maintenance_due_at TIMESTAMP NOT NULL,
        reminder_sent_at TIMESTAMP,
        review_requested_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    op.execute('''
    CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        actor_user_id INTEGER REFERENCES "user"(id),
        action VARCHAR(100) NOT NULL,
        details TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    op.execute('''
    CREATE TABLE IF NOT EXISTS app_setting (
        id SERIAL PRIMARY KEY,
        key VARCHAR(100) NOT NULL UNIQUE,
        value TEXT NOT NULL DEFAULT '',
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    ''')


def downgrade():
    # Keep downgrade no-op for baseline to avoid accidental destructive rollback.
    pass
