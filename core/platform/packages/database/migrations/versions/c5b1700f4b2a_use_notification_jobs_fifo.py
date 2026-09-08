"""Use the notification FIFO queue for the notification sweeper.

Revision ID: c5b1700f4b2a
Revises: adee9680c2ed
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5b1700f4b2a"
down_revision: str | Sequence[str] | None = "adee9680c2ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE scheduling.scheduled_jobs
        SET target_queue = 'notification-jobs.fifo', updated_at = NOW()
        WHERE id = 'job_notif_sweeper'
          AND target_queue IN ('notification-jobs', 'edi-priority-notifications')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE scheduling.scheduled_jobs
        SET target_queue = 'edi-priority-notifications', updated_at = NOW()
        WHERE id = 'job_notif_sweeper'
          AND target_queue = 'notification-jobs.fifo'
        """
    )
