"""Status como Enum estricto, order_id y ship_request

Revision ID: a7f3c2d91e10
Revises: 9c6c788bc7ac
Create Date: 2026-11-05 15:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f3c2d91e10'
down_revision: Union[str, Sequence[str], None] = '9c6c788bc7ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES = ('PENDING_PAYMENT', 'PAID', 'LABEL_CREATED', 'IN_TRANSIT', 'DELIVERED', 'CANCELED')
shipment_status = sa.Enum(*STATUSES, name='shipment_status')


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Nuevas columnas
    op.add_column('shipments', sa.Column('order_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_shipments_order_id'), 'shipments', ['order_id'], unique=True)
    op.add_column('shipments', sa.Column('ship_request', sa.JSON(), nullable=True))

    # 2. Normalizar valores legados ("pending", NULL, etc.) antes de convertir el tipo
    allowed = ", ".join(f"'{s}'" for s in STATUSES)
    op.execute(
        f"UPDATE shipments SET status = 'PENDING_PAYMENT' "
        f"WHERE status IS NULL OR status NOT IN ({allowed})"
    )

    # 3. String -> Enum de Postgres
    shipment_status.create(op.get_bind(), checkfirst=True)
    op.alter_column(
        'shipments', 'status',
        existing_type=sa.String(),
        type_=shipment_status,
        postgresql_using='status::shipment_status',
        nullable=False,
        server_default='PENDING_PAYMENT',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'shipments', 'status',
        existing_type=shipment_status,
        type_=sa.String(),
        postgresql_using='status::text',
        nullable=True,
        server_default=None,
    )
    shipment_status.drop(op.get_bind(), checkfirst=True)
    op.drop_column('shipments', 'ship_request')
    op.drop_index(op.f('ix_shipments_order_id'), table_name='shipments')
    op.drop_column('shipments', 'order_id')
