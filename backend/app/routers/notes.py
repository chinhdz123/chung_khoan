from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import InvestmentNote
from app.schemas import NoteCreate, NoteResponse, NoteUpdate
from app.services.user_service import get_default_user

router = APIRouter(prefix="/api/notes", tags=["Notes"])


@router.get("", response_model=list[NoteResponse])
def get_notes(symbol: str | None = None, db: Session = Depends(get_db)):
    user = get_default_user(db)
    query = db.query(InvestmentNote).filter(InvestmentNote.user_id == user.id)
    if symbol:
        query = query.filter(InvestmentNote.symbol == symbol.upper())
    
    notes = query.order_by(InvestmentNote.created_at.desc()).all()
    return notes


@router.post("", response_model=NoteResponse)
def create_note(note_in: NoteCreate, db: Session = Depends(get_db)):
    user = get_default_user(db)
    
    new_note = InvestmentNote(
        user_id=user.id,
        symbol=note_in.symbol.upper() if note_in.symbol else None,
        tags_json=note_in.tags_json,
        content=note_in.content
    )
    db.add(new_note)
    db.commit()
    db.refresh(new_note)
    return new_note


@router.put("/{note_id}", response_model=NoteResponse)
def update_note(note_id: int, note_in: NoteUpdate, db: Session = Depends(get_db)):
    user = get_default_user(db)
    note = db.query(InvestmentNote).filter(
        InvestmentNote.id == note_id,
        InvestmentNote.user_id == user.id
    ).first()
    
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
        
    note.symbol = note_in.symbol.upper() if note_in.symbol else None
    note.tags_json = note_in.tags_json
    note.content = note_in.content
    
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    user = get_default_user(db)
    note = db.query(InvestmentNote).filter(
        InvestmentNote.id == note_id,
        InvestmentNote.user_id == user.id
    ).first()
    
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
        
    db.delete(note)
    db.commit()
    return {"ok": True}
