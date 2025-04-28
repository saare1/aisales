from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.api.models import (
    LeadCreate, 
    LeadUpdate, 
    LeadResponse, 
    IncomingMessage, 
    AgentResponse,
    ConversationResponse,
    ProductRecommendationResponse
)
from app.services.agent import SalesCloserAgent
from app.services.memory import MemoryManager
from app.services.scheduler import SchedulerService
from app.db.models import Lead, LeadStatus, ConversationChannel
from app.db.database import get_db
from app.services.product_recommendation import ProductRecommendationEngine
import os

router = APIRouter()
sales_agent = SalesCloserAgent()

# Initialize product recommendation engine
product_recommendation_engine = ProductRecommendationEngine(None, os.getenv("OPENAI_API_KEY"))

@router.post("/leads/", response_model=LeadResponse)
def create_lead(
    lead: LeadCreate,
    auto_greet: bool = True,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Create a new lead and optionally send an automated greeting.
    """
    # Check if lead with this email already exists
    existing_lead = MemoryManager.get_lead_by_email(lead.email, db)
    if existing_lead:
        raise HTTPException(status_code=400, detail="Lead with this email already exists")
    
    # Create new lead
    new_lead = Lead(
        first_name=lead.first_name,
        last_name=lead.last_name,
        email=lead.email,
        phone=lead.phone,
        company=lead.company,
        job_title=lead.job_title,
        source=lead.source,
        notes=lead.notes,
        preferred_channel=lead.preferred_channel,
        status=LeadStatus.NEW,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_active=True
    )
    
    db.add(new_lead)
    db.commit()
    db.refresh(new_lead)
    
    # Send automated greeting if requested
    if auto_greet and background_tasks:
        background_tasks.add_task(sales_agent.greet_lead, new_lead, db)
    
    return new_lead


@router.get("/leads/", response_model=List[LeadResponse])
def get_leads(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    db: Session = Depends(get_db)
):
    """
    Get a list of leads, with optional filtering by status.
    """
    query = db.query(Lead)
    
    if status:
        try:
            query = query.filter(Lead.status == LeadStatus(status))
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid status. Valid values are: {', '.join([s.value for s in LeadStatus])}"
            )
    
    return query.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """
    Get details of a specific lead by ID.
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.put("/leads/{lead_id}", response_model=LeadResponse)
def update_lead(
    lead_id: int,
    lead_update: LeadUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a lead's information.
    """
    # Get the lead
    db_lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Update the lead fields
    lead_data = lead_update.dict(exclude_unset=True)
    for key, value in lead_data.items():
        if value is not None:
            setattr(db_lead, key, value)
    
    # Update timestamp
    db_lead.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_lead)
    
    return db_lead


@router.post("/leads/{lead_id}/message", response_model=AgentResponse)
async def handle_lead_message(
    lead_id: int,
    message: IncomingMessage,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Handle an incoming message from a lead and generate an agent response.
    """
    # Get the lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Validate the email matches
    if lead.email != message.lead_email:
        raise HTTPException(status_code=400, detail="Email does not match lead record")
    
    # Process the message in the background
    result = sales_agent.handle_message(
        lead.email,
        message.content,
        message.channel,
        db
    )
    
    # Return the agent's response
    return AgentResponse(
        content=result["response"],
        scheduled_actions=[a["action"] for a in result.get("actions", []) if a.get("success")]
    )


@router.post("/leads/{lead_id}/greet", response_model=AgentResponse)
async def send_greeting(
    lead_id: int,
    db: Session = Depends(get_db)
):
    """
    Send a greeting message to a lead.
    """
    # Get the lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Send the greeting
    result = sales_agent.greet_lead(lead, db)
    
    # Return the agent's greeting
    return AgentResponse(
        content=result["greeting"],
        scheduled_actions=[a["action"] for a in result.get("actions", []) if a.get("success")]
    )


@router.post("/leads/{lead_id}/follow-up", response_model=AgentResponse)
async def send_followup(
    lead_id: int,
    db: Session = Depends(get_db)
):
    """
    Send a follow-up message to a lead.
    """
    # Get the lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Send the follow-up
    result = sales_agent.follow_up_lead(lead_id, db)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=400, 
            detail=f"Could not send follow-up: {result.get('reason', 'Unknown reason')}"
        )
    
    # Return the agent's follow-up
    return AgentResponse(
        content=result["followup"],
        scheduled_actions=[a["action"] for a in result.get("actions", []) if a.get("success")]
    )


@router.post("/leads/{lead_id}/close", response_model=AgentResponse)
async def close_sale(
    lead_id: int,
    db: Session = Depends(get_db)
):
    """
    Send a closing message to a lead.
    """
    # Get the lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Send the closing message
    result = sales_agent.close_sale(lead_id, db)
    
    # Return the agent's closing message
    return AgentResponse(
        content=result["closing"],
        scheduled_actions=[a["action"] for a in result.get("actions", []) if a.get("success")]
    )


@router.post("/messages/process-pending", response_model=dict)
async def process_pending_messages(
    db: Session = Depends(get_db)
):
    """
    Process all pending scheduled messages (like follow-ups).
    
    This would typically be called by a cron job.
    """
    # Execute all pending actions
    results = SchedulerService.execute_pending_actions(db)
    
    return {
        "success": True,
        "processed_count": len(results),
        "results": results
    }


@router.get("/leads/{lead_id}/conversations", response_model=List[ConversationResponse])
def get_lead_conversations(
    lead_id: int,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Get the conversation history for a lead.
    """
    # Get the lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Get the conversation history
    conversations = MemoryManager.get_lead_history(lead_id, limit, db)
    
    return conversations


@router.post("/webhook/incoming-message", response_model=dict)
async def webhook_incoming_message(
    message: IncomingMessage,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Webhook for handling incoming messages from external services.
    
    This could be integrated with SendGrid, Twilio, etc.
    """
    # Get the lead
    lead = MemoryManager.get_lead_by_email(message.lead_email, db)
    if not lead:
        # Create a new lead if this is a new email
        lead = Lead(
            first_name="Unknown",  # These would be filled in later
            last_name="Lead",
            email=message.lead_email,
            preferred_channel=message.channel,
            status=LeadStatus.NEW,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_active=True
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
    
    # Process the message in the background
    background_tasks.add_task(
        sales_agent.handle_message,
        lead.email,
        message.content,
        message.channel,
        db
    )
    
    return {"success": True, "message": "Message received and being processed"}


# Product recommendation endpoints
@router.get("/leads/{lead_id}/recommendations", response_model=List[ProductRecommendationResponse])
def get_lead_recommendations(
    lead_id: int,
    db: Session = Depends(get_db)
):
    """
    Get product recommendations for a specific lead.
    """
    # Get the lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Initialize recommendation engine with current db session
    product_recommendation_engine.db = db
    
    # Get recommendations
    recommendations = product_recommendation_engine.get_lead_recommendations(lead_id)
    
    return recommendations

@router.post("/leads/{lead_id}/recommendations", response_model=List[ProductRecommendationResponse])
def generate_lead_recommendations(
    lead_id: int,
    max_recommendations: int = 3,
    db: Session = Depends(get_db)
):
    """
    Generate fresh product recommendations for a lead based on their conversation history and preferences.
    """
    # Get the lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Initialize recommendation engine with current db session
    product_recommendation_engine.db = db
    
    # Generate recommendations
    recommendations = product_recommendation_engine.generate_recommendations(lead_id, max_recommendations)
    
    # Retrieve the saved recommendations in response format
    return product_recommendation_engine.get_lead_recommendations(lead_id)

@router.put("/recommendations/{recommendation_id}", response_model=dict)
def update_recommendation_status(
    recommendation_id: int,
    accepted: bool,
    db: Session = Depends(get_db)
):
    """
    Mark a product recommendation as accepted or rejected by the lead.
    """
    # Initialize recommendation engine with current db session
    product_recommendation_engine.db = db
    
    # Update recommendation status
    success = product_recommendation_engine.mark_recommendation_accepted(recommendation_id, accepted)
    
    if not success:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    
    return {"success": True, "recommendation_id": recommendation_id, "accepted": accepted} 