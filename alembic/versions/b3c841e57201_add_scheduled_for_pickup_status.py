"""Add SCHEDULED_FOR_PICKUP to shipment_status enum

Revision ID: b3c841e57201
Revises: 148f97980444
Create Date: 2026-11-06 21:00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b3c841e57201'
down_revision: Union[str, Sequence[str], None] = '148f97980444'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # En PostgreSQL, ALTER TYPE ... ADD VALUE no puede ejecutarse dentro de un bloque de transacción
    # estándar en algunas versiones, por lo que usamos autocommit_block().
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE shipment_status ADD VALUE IF NOT EXISTS 'SCHEDULED_FOR_PICKUP' AFTER 'LABEL_CREATED'")


def downgrade() -> None:
    # PostgreSQL no permite remover un valor de un enum fácilmente sin recrearlo.
    pass
