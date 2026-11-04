"""Crear tabla shipments

Revision ID: 9c6c788bc7ac
Revises: c1439138140c
Create Date: 2026-11-04 21:32:36.189540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c6c788bc7ac'
down_revision: Union[str, Sequence[str], None] = 'c1439138140c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
