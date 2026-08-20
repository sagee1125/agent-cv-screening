"""${message}."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


# Apply this schema revision.
def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


# Revert this schema revision.
def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
