"""Tag CRUD endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from src.database.models import Tag, PositionGroupTag
from src.database.db_manager import DatabaseManager
from src.dependencies import get_db, get_current_user_id
from src.schemas import TagCreate, TagUpdate

router = APIRouter()


@router.get("/api/tags")
async def list_tags(db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """List all tags for the current user."""
    with db.get_session() as session:
        rows = session.query(Tag).order_by(Tag.name.asc()).all()
        return [
            {"id": t.id, "name": t.name, "color": t.color or "#3B82F6"}
            for t in rows
        ]


@router.post("/api/tags")
async def create_tag(body: TagCreate, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Create a new tag."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")

    with db.get_session() as session:
        existing = session.query(Tag).filter(Tag.name == name).first()
        if existing:
            return {"id": existing.id, "name": existing.name, "color": existing.color or "#3B82F6"}

        tag = Tag(name=name, color=body.color or "#3B82F6")
        session.add(tag)
        session.flush()
        return {"id": tag.id, "name": tag.name, "color": tag.color}


@router.put("/api/tags/{tag_id}")
async def update_tag(tag_id: int, body: TagUpdate, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Update a tag's name or color."""
    with db.get_session() as session:
        tag = session.query(Tag).filter(Tag.id == tag_id).first()
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        if body.name is not None:
            tag.name = body.name.strip()
        if body.color is not None:
            tag.color = body.color
        tag.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        return {"id": tag.id, "name": tag.name, "color": tag.color}


@router.delete("/api/tags/{tag_id}")
async def delete_tag(tag_id: int, db: DatabaseManager = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Delete a tag and all its associations."""
    with db.get_session() as session:
        tag = session.query(Tag).filter(Tag.id == tag_id).first()
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        session.query(PositionGroupTag).filter(PositionGroupTag.tag_id == tag_id).delete()
        session.delete(tag)

    return {"message": "Tag deleted"}
