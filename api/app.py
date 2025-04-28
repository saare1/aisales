from fastapi import FastAPI, HTTPException, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import Dict, Any
import os
import sys

# Add the project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import get_db_session
from app.db.models import ConversationChannel, Lead, LeadStatus
from app.services.agent import SalesCloserAgent
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="AI Sales Closer API",
    description="API for interacting with the AI Sales Closer Agent",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the agent
openai_api_key = os.getenv("OPENAI_API_KEY")
sales_agent = SalesCloserAgent(openai_api_key=openai_api_key)

@app.post("/api/v1/chat")
async def chat_with_agent(
    data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db_session)
):
    """
    Chat with the AI Sales Closer Agent.
    
    Args:
        data: JSON object containing:
            - message: The message from the user
            - lead_email: Email of the lead
            - channel: Communication channel (optional, defaults to WEBCHAT)
        db: Database session
        
    Returns:
        JSON response with agent's reply
    """
    try:
        # Extract data from request
        message = data.get("message")
        lead_email = data.get("lead_email")
        channel_str = data.get("channel", "WEBCHAT")
        
        # Validate inputs
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")
        if not lead_email:
            raise HTTPException(status_code=400, detail="Lead email is required")
        
        # Convert channel string to enum
        try:
            channel = ConversationChannel(channel_str)
        except ValueError:
            channel = ConversationChannel.WEBCHAT
        
        # Get or create lead
        lead = db.query(Lead).filter(Lead.email == lead_email).first()
        if not lead:
            # Create new lead if not exists
            lead = Lead(
                email=lead_email,
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                company=data.get("company", ""),
                job_title=data.get("job_title", ""),
                source="Website Chat",
                status=LeadStatus.NEW,
                preferred_channel=channel
            )
            db.add(lead)
            db.commit()
            db.refresh(lead)
            
            # Send greeting to new lead
            greeting_result = sales_agent.greet_lead(lead, db)
            initial_message = greeting_result.get("greeting", "Hello! How can I assist you today?")
            
            return {
                "success": True,
                "is_new_lead": True,
                "response": initial_message,
                "lead_id": lead.id
            }
        
        # Process message through agent
        result = sales_agent.handle_message(
            lead_email=lead_email,
            message_content=message,
            channel=channel,
            db=db
        )
        
        # Check if compliance issue was detected
        if result.get("compliance_issue", False):
            return {
                "success": True,
                "compliance_issue": True,
                "response": result.get("response", "I'll connect you with a human representative."),
                "lead_id": lead.id
            }
        
        # Return the agent's response
        return {
            "success": True,
            "response": result.get("response", ""),
            "lead_id": lead.id,
            "actions": result.get("actions", [])
        }
        
    except Exception as e:
        # Log the error and return a generic error message
        import logging
        logging.error(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@app.post("/api/v1/leads")
async def create_lead(
    data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db_session)
):
    """
    Create a new lead.
    
    Args:
        data: JSON object containing lead information
        db: Database session
        
    Returns:
        JSON response with lead information
    """
    try:
        # Extract data from request
        email = data.get("email")
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        company = data.get("company", "")
        job_title = data.get("job_title", "")
        source = data.get("source", "Website")
        
        # Validate inputs
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        # Check if lead already exists
        existing_lead = db.query(Lead).filter(Lead.email == email).first()
        if existing_lead:
            return {
                "success": True,
                "message": "Lead already exists",
                "lead_id": existing_lead.id
            }
        
        # Create new lead
        lead = Lead(
            email=email,
            first_name=first_name,
            last_name=last_name,
            company=company,
            job_title=job_title,
            source=source,
            status=LeadStatus.NEW,
            preferred_channel=ConversationChannel.EMAIL
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        
        return {
            "success": True,
            "message": "Lead created successfully",
            "lead_id": lead.id
        }
        
    except Exception as e:
        # Log the error and return a generic error message
        import logging
        logging.error(f"Error creating lead: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

# Run the app with uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 