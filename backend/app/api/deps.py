"""Shared router dependencies."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import NotFound
from app.core.security import get_current_user
from app.models import Project, User


def get_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Project:
    project = db.get(Project, project_id)
    if not project or project.organization_id != user.organization_id:
        raise NotFound("Project not found.", "المشروع غير موجود.")
    return project
