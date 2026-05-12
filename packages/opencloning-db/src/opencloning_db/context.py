"""Lightweight value objects shared between the auth, persistence, and model layers."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opencloning_db.models import User


@dataclass(frozen=True, slots=True)
class WriteContext:
    """Identity for any write/create operation: who is acting, in which workspace."""

    user: 'User'
    workspace_id: int
