"""Added Index to ensure template sequence names are unique within a workspace

Revision ID: 3f575f16956b
Revises:
Create Date: 2026-05-26 12:17:36.587416

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3f575f16956b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'uq_input_entity_template_sequence_workspace_name',
        'input_entity',
        ['workspace_id', sa.literal_column('lower(name)')],
        unique=True,
        postgresql_where=sa.text("type = 'template_sequence'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'uq_input_entity_template_sequence_workspace_name',
        table_name='input_entity',
        postgresql_where=sa.text("type = 'template_sequence'"),
    )
