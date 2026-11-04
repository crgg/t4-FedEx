"""Crear tabla shipments

Revision ID: c1439138140c
Revises: 9a87d445d823
Create Date: 2026-11-04 19:24:09.409245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1439138140c'
down_revision: Union[str, Sequence[str], None] = '9a87d445d823'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
