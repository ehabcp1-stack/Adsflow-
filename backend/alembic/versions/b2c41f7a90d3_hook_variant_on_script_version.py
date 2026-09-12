"""record which hook variant a script version adopted

Hook testing produces several creatives that differ only in their first three
seconds. Without this column a campaign report can tell you which creative won
but not which opening it was carrying, which is the one thing the test exists
to learn.

Revision ID: b2c41f7a90d3
Revises: 038f8d06c9a8
Create Date: 2026-09-12
"""
import sqlalchemy as sa
from alembic import op

revision = "b2c41f7a90d3"
down_revision = "038f8d06c9a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("script_versions", sa.Column("hook_variant", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("script_versions", "hook_variant")
