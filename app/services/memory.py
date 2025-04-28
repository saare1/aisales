from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.db.models import Lead, Conversation, LeadStatus, ConversationChannel
from app.db.database import get_db_session


class MemoryManager:
    """
    Manages the storage and retrieval of conversation memory for the sales agent.
    """
    
    @staticmethod
    def get_lead_by_email(email: str, db: Session = None) -> Optional[Lead]:
        """Get a lead by their email address."""
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
            
        try:
            return db.query(Lead).filter(Lead.email == email).first()
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def get_lead_history(lead_id: int, limit: int = 10, db: Session = None) -> List[Conversation]:
        """Get the conversation history for a lead, ordered by timestamp."""
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
            
        try:
            return (
                db.query(Conversation)
                .filter(Conversation.lead_id == lead_id)
                .order_by(Conversation.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def add_message(
        lead_id: int,
        content: str,
        is_from_lead: bool,
        channel: ConversationChannel,
        db: Session = None
    ) -> Conversation:
        """Add a new message to the conversation history."""
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
            
        try:
            # Create the new conversation entry
            new_message = Conversation(
                lead_id=lead_id,
                content=content,
                is_from_lead=is_from_lead,
                channel=channel,
                created_at=datetime.utcnow()
            )
            
            # Update the lead's last_contact timestamp
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                lead.last_contact = datetime.utcnow()
                if not is_from_lead:  # If agent is sending a message, reset followup count
                    lead.followup_count = 0
            
            db.add(new_message)
            db.commit()
            db.refresh(new_message)
            
            return new_message
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def format_conversation_history(conversations: List[Conversation]) -> str:
        """Format conversation history into a string for the agent to use."""
        if not conversations:
            return "No previous conversation history."
        
        # Reverse to get chronological order
        conversations = sorted(conversations, key=lambda c: c.created_at)
        
        formatted_history = []
        for msg in conversations:
            speaker = "Lead" if msg.is_from_lead else "Agent"
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
            formatted_history.append(f"[{timestamp}] {speaker}: {msg.content}")
        
        return "\n".join(formatted_history)
    
    @staticmethod
    def get_lead_context(lead_id: int, db: Session = None) -> Dict[str, Any]:
        """Get all relevant context about a lead for the agent."""
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
            
        try:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                return {"error": "Lead not found"}
            
            # Get conversation history
            conversations = MemoryManager.get_lead_history(lead_id, limit=10, db=db)
            formatted_history = MemoryManager.format_conversation_history(conversations)
            
            # Create a comprehensive context object
            context = {
                "lead_id": lead.id,
                "name": lead.full_name,
                "first_name": lead.first_name,
                "email": lead.email,
                "phone": lead.phone,
                "company": lead.company,
                "job_title": lead.job_title,
                "status": lead.status.value,
                "source": lead.source,
                "notes": lead.notes,
                "budget": lead.budget,
                "needs": lead.needs,
                "objections": lead.objections,
                "preferred_channel": lead.preferred_channel.value,
                "created_at": lead.created_at.isoformat(),
                "last_contact": lead.last_contact.isoformat() if lead.last_contact else None,
                "followup_count": lead.followup_count,
                "days_since_creation": (datetime.utcnow() - lead.created_at).days,
                "days_since_last_contact": (datetime.utcnow() - lead.last_contact).days if lead.last_contact else None,
                "conversation_history": formatted_history
            }
            
            return context
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def update_lead_status(lead_id: int, new_status: LeadStatus, db: Session = None) -> Lead:
        """Update the status of a lead."""
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
            
        try:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                lead.status = new_status
                lead.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(lead)
            return lead
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def update_lead_info(
        lead_id: int, 
        updates: Dict[str, Any],
        db: Session = None
    ) -> Lead:
        """Update lead information based on conversation insights."""
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
            
        try:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                return None
                
            for key, value in updates.items():
                if hasattr(lead, key) and value is not None:
                    setattr(lead, key, value)
            
            lead.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(lead)
            return lead
        finally:
            if close_db:
                db.close()
                
    @staticmethod
    def increment_followup_count(lead_id: int, db: Session = None) -> int:
        """Increment the followup count for a lead."""
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
            
        try:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                lead.followup_count += 1
                db.commit()
                return lead.followup_count
            return 0
        finally:
            if close_db:
                db.close() 