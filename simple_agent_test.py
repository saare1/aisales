import os
import sys
from dotenv import load_dotenv
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Add the project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def main():
    """Simple test to create an agent instance and test the compliance guardrails."""
    try:
        # Import agent
        logger.info("Importing SalesCloserAgent...")
        from app.services.agent import SalesCloserAgent
        
        # Create agent instance
        logger.info("Creating agent instance...")
        agent = SalesCloserAgent(openai_api_key="test_key")
        logger.info("Agent created successfully!")
        
        # Import compliance guardrails
        logger.info("Importing ComplianceGuardrails...")
        from app.services.compliance_guardrails import ComplianceGuardrails
        
        # Test compliance check
        test_message = "I want to evade taxes illegally."
        logger.info(f"Testing compliance check with message: '{test_message}'")
        
        is_compliant, risk_category, detected_phrases = ComplianceGuardrails.check_message_compliance(test_message)
        
        logger.info(f"Is compliant: {is_compliant}")
        if not is_compliant:
            logger.info(f"Risk category: {risk_category}")
            logger.info(f"Detected phrases: {detected_phrases}")
            
            # Get compliance response
            response = ComplianceGuardrails.get_compliance_response(risk_category)
            logger.info(f"Compliance response: {response}")
        
    except Exception as e:
        logger.error(f"Error in test: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 