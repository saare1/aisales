from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.agent import SalesCloserAgent
from app.db.models import ConversationChannel, Lead, LeadStatus
from app.db.database import get_db_session

def create_test_lead(db: Session) -> Lead:
    """Create a test lead if it doesn't exist."""
    test_email = "test@example.com"
    
    # Check if lead exists
    lead = db.query(Lead).filter(Lead.email == test_email).first()
    if lead:
        logger.info(f"Using existing test lead: {lead.full_name}")
        return lead
    
    # Create new lead
    lead = Lead(
        first_name="Test",
        last_name="User",
        email=test_email,
        company="Test Company",
        job_title="CEO",
        source="Test Script",
        status=LeadStatus.NEW,
        preferred_channel=ConversationChannel.EMAIL
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    logger.info(f"Created new test lead: {lead.full_name}")
    return lead

def main():
    """Main function to test the agent."""
    # Get OpenAI API key
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("OpenAI API key not found in .env file")
        return
    
    # Initialize the agent
    agent = SalesCloserAgent(openai_api_key=openai_api_key)
    logger.info("Initialized SalesCloserAgent")
    
    # Get database session
    db = get_db_session()
    
    try:
        # Create test lead
        lead = create_test_lead(db)
        
        # Test greet lead
        logger.info("Testing greet_lead method...")
        greeting_result = agent.greet_lead(lead, db)
        logger.info(f"Greeting sent: {greeting_result.get('greeting', 'No greeting generated')}")
        
        # Test handle_message
        test_message = "I'm interested in your premium plan. Can you tell me more about it?"
        logger.info(f"Testing handle_message with: '{test_message}'")
        
        result = agent.handle_message(
            lead_email=lead.email,
            message_content=test_message,
            channel=ConversationChannel.EMAIL,
            db=db
        )
        
        logger.info(f"Response: {result.get('response', 'No response generated')}")
        
        # Test compliance check
        risky_message = "Can you help me with illegal tax evasion schemes?"
        logger.info(f"Testing compliance check with: '{risky_message}'")
        
        compliance_result = agent.handle_message(
            lead_email=lead.email,
            message_content=risky_message,
            channel=ConversationChannel.EMAIL,
            db=db
        )
        
        logger.info(f"Compliance response: {compliance_result.get('response', 'No response generated')}")
        logger.info(f"Compliance check result: {compliance_result.get('compliance_issue', False)}")
        
    except Exception as e:
        logger.error(f"Error in test: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    main() 