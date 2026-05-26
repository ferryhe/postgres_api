"""Scope HK life product identity to project.

Revision ID: 0002_project_scoped_product_identity
Revises: 0001_initial_schema
Create Date: 2026-05-27 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_project_scoped_product_identity"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hk_life_products") as batch_op:
        batch_op.drop_constraint("uq_hk_life_products_insurer_name", type_="unique")
        batch_op.create_unique_constraint(
            "uq_hk_life_products_project_insurer_name",
            ["project_id", "insurer_id", "canonical_name"],
        )


def downgrade() -> None:
    with op.batch_alter_table("hk_life_products") as batch_op:
        batch_op.drop_constraint("uq_hk_life_products_project_insurer_name", type_="unique")
        batch_op.create_unique_constraint(
            "uq_hk_life_products_insurer_name",
            ["insurer_id", "canonical_name"],
        )
