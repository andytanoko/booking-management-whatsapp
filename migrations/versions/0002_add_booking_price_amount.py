"""add booking price amount

Revision ID: 0002_price_amount
Revises: 0001_baseline
Create Date: 2026-08-10 00:05:00

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '0002_price_amount'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def upgrade():
    # Compatibility guard: baseline now includes this column, but older databases
    # that already applied 0001 before this change still need the ALTER.
    op.execute('ALTER TABLE booking ADD COLUMN IF NOT EXISTS price_amount NUMERIC(12,2)')


def downgrade():
    op.execute('ALTER TABLE booking DROP COLUMN IF EXISTS price_amount')
