"""Crear tabla shipments

Revision ID: db402a603249
Revises: a7f3c2d91e10
Create Date: 2026-11-05 22:00:42.264371

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db402a603249'
down_revision: Union[str, Sequence[str], None] = 'a7f3c2d91e10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
