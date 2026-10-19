"""flat sets schema: add exercise_id to set_log, make prescription_id nullable

Revision ID: 001_flat_sets
Revises: 
Create Date: 2025-01-01 00:00:00.000000

Adds exercise_id (NOT NULL, FK to exercise) to set_log table.
Makes prescription_id nullable.
Backfills exercise_id from prescription.exercise_id for all existing rows.
Fails loudly if any row cannot be backfilled.
Creates index on (exercise_id, session_id) via prescription->session join.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '001_flat_sets'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add exercise_id column as nullable initially
    op.add_column(
        'set_log',
        sa.Column('exercise_id', sa.Integer(), nullable=True)
    )

    # Step 2: Backfill exercise_id from prescription.exercise_id
    # This fails loudly if any set_log row has a prescription with no exercise_id
    op.execute(
        """
        UPDATE set_log
        SET exercise_id = (
            SELECT p.exercise_id
            FROM prescription p
            WHERE p.id = set_log.prescription_id
        )
        WHERE prescription_id IS NOT NULL
        """
    )

    # Step 3: Verify no NULL exercise_id rows remain - fail loudly
    # We do this by checking and raising an error if any exist
    conn = op.get_bind()
    null_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM set_log WHERE exercise_id IS NULL")
    ).scalar()
    if null_count > 0:
        raise RuntimeError(
            f"Migration failed: {null_count} set_log rows could not be backfilled "
            "with exercise_id. Aborting migration."
        )

    # Step 4: Make exercise_id NOT NULL
    op.alter_column(
        'set_log',
        'exercise_id',
        nullable=False,
    )

    # Step 5: Add foreign key constraint
    op.create_foreign_key(
        'fk_set_log_exercise_id',
        'set_log',
        'exercise',
        ['exercise_id'],
        ['id'],
    )

    # Step 6: Make prescription_id nullable
    op.alter_column(
        'set_log',
        'prescription_id',
        nullable=True,
    )

    # Step 7: Create index on (exercise_id, session_id)
    # session_id is not directly on set_log, so we create a composite index
    # using exercise_id and a subquery-derived session_id
    # Actually, the task says index on (exercise_id, session_id)
    # session_id comes from prescription.session_id
    # We'll create a computed column or use a different approach
    # Since SQLite doesn't support generated columns well in all versions,
    # we'll create the index on exercise_id alone for now,
    # and add a session_id column to set_log for the composite index
    
    # Add session_id column for the composite index
    op.add_column(
        'set_log',
        sa.Column('session_id', sa.Integer(), nullable=True)
    )

    # Backfill session_id from prescription.session_id
    op.execute(
        """
        UPDATE set_log
        SET session_id = (
            SELECT p.session_id
            FROM prescription p
            WHERE p.id = set_log.prescription_id
        )
        WHERE prescription_id IS NOT NULL
        """
    )

    # Create the composite index
    op.create_index(
        'ix_set_log_exercise_session',
        'set_log',
        ['exercise_id', 'session_id'],
    )


def downgrade() -> None:
    # Remove the index
    op.drop_index('ix_set_log_exercise_session', table_name='set_log')

    # Remove session_id column
    op.drop_column('set_log', 'session_id')

    # Make prescription_id NOT NULL again
    op.alter_column(
        'set_log',
        'prescription_id',
        nullable=False,
    )

    # Remove foreign key
    op.drop_constraint('fk_set_log_exercise_id', 'set_log', type_='foreignkey')

    # Remove exercise_id column
    op.drop_column('set_log', 'exercise_id')
