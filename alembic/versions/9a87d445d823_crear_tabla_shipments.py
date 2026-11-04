"""Crear tabla shipments

Revision ID: 9a87d445d823
Revises: 2ed24b235d00
Create Date: 2026-11-04 19:15:32.655377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a87d445d823'
down_revision: Union[str, Sequence[str], None] = '2ed24b235d00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
