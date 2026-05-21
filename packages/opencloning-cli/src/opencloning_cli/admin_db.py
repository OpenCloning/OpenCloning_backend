"""Direct database access for admin CLI commands."""

from __future__ import annotations

from typing import Any

import opencloning_db.db as db_module
from sqlalchemy import select
from sqlalchemy.orm import Session

from opencloning_db.auth.invites import normalize_email
from fastapi import HTTPException
from opencloning_db.config import get_config
from opencloning_db.db_utils import get_workspace_or_404
from opencloning_db.models import User, Workspace, WorkspaceMembership, WorkspaceRole


def _parse_workspace_role(role: str) -> WorkspaceRole:
    try:
        return WorkspaceRole(role)
    except ValueError as exc:
        raise RuntimeError(f'Invalid role: {role}') from exc


def list_user_emails() -> list[str]:
    config = get_config()
    with Session(db_module.get_engine(config)) as session:
        emails = session.scalars(select(User.email).order_by(User.email.asc())).all()
        return sorted(emails)


def list_workspaces() -> list[dict[str, Any]]:
    config = get_config()
    with Session(db_module.get_engine(config)) as session:
        workspaces = session.scalars(select(Workspace).order_by(Workspace.id.asc())).all()
        return [{'id': workspace.id, 'name': workspace.name} for workspace in workspaces]


def assign_user_to_workspace(email: str, workspace_id: int, role: str) -> dict[str, Any]:
    config = get_config()
    normalized_email = normalize_email(email)
    workspace_role = _parse_workspace_role(role)

    with Session(db_module.get_engine(config)) as session:
        try:
            get_workspace_or_404(session, workspace_id)
        except HTTPException as exc:
            raise RuntimeError('Workspace not found') from exc

        user = session.scalar(select(User).where(User.email == normalized_email))
        if user is None:
            raise RuntimeError('User not found')

        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.workspace_id == workspace_id,
            )
        )
        if membership is None:
            membership = WorkspaceMembership(
                user_id=user.id,
                workspace_id=workspace_id,
                role=workspace_role,
            )
            session.add(membership)
        else:
            membership.role = workspace_role
        session.commit()
        return {
            'user_id': user.id,
            'workspace_id': workspace_id,
            'role': membership.role.value,
        }
