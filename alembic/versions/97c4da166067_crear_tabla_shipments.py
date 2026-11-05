"""Crear tabla shipments

Revision ID: 97c4da166067
Revises: db402a603249
Create Date: 2026-11-05 22:05:55.669227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97c4da166067'
down_revision: Union[str, Sequence[str], None] = 'db402a603249'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
