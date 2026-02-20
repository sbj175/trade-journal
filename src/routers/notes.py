"""Order comment and position note routes."""

from fastapi import APIRouter, HTTPException

from src.dependencies import db
from src.schemas import OrderCommentUpdate, PositionNoteUpdate

router = APIRouter()


@router.get("/api/order-comments")
async def get_order_comments():
    """Get all order comments"""
    comments = db.get_all_order_comments()
    return {"comments": comments}


@router.put("/api/order-comments/{order_id}")
async def save_order_comment(order_id: str, body: OrderCommentUpdate):
    """Save or delete a comment for an order"""
    success = db.save_order_comment(order_id, body.comment)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save comment")
    return {"message": "Comment saved"}


@router.get("/api/position-notes")
async def get_position_notes():
    """Get all position notes"""
    notes = db.get_all_position_notes()
    return {"notes": notes}


@router.put("/api/position-notes/{note_key:path}")
async def save_position_note(note_key: str, body: PositionNoteUpdate):
    """Save or delete a note for a position"""
    success = db.save_position_note(note_key, body.note)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save note")
    return {"message": "Note saved"}
