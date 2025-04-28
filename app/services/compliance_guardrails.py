import logging
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from sqlalchemy.orm import Session

from ..db.models import Lead, Conversation, ComplianceRiskCategory, ComplianceLog
from ..services.messaging import MessagingService

logger = logging.getLogger(__name__)

class ComplianceGuardrails:
    """
    Service for analyzing messages for compliance risks and handling risky interactions.
    """
    
    # Default risk patterns - can be overridden or extended
    DEFAULT_RISK_PATTERNS = {
        ComplianceRiskCategory.ILLEGAL_ACTIVITY: [
            r"\b(illegal|illicit|criminal)\s+(activity|activities|operation|deal)",
            r"\b(drug|weapon|human)\s+(trafficking|smuggling|trade)",
            r"\blaunder(ing)?\s+(money|cash|funds)",
            r"\b(evad(e|ing)|avoid(ing)?)\s+(tax(es)?|sanctions|regulations)"
        ],
        ComplianceRiskCategory.PRIVACY_VIOLATION: [
            r"\b(steal|hack|obtain|extract)\s+(personal|private|sensitive)\s+(data|information)",
            r"\b(bypass|circumvent)\s+(security|authentication|verification)",
            r"\baccess\s+(unauthorized|restricted)\s+(data|systems|accounts)",
            r"\b(spy|monitor|track)\s+without\s+(consent|permission|knowledge)"
        ],
        ComplianceRiskCategory.FINANCIAL_FRAUD: [
            r"\b(pyramid|ponzi)\s+scheme",
            r"\bfalse\s+(investment|return|profit)",
            r"\b(fake|phishing|scam)\s+(website|payment|invoice)",
            r"\bidentity\s+theft",
            r"\bcounterfeit\s+(money|currency|goods)",
            r"\bfraudul(ent|ently)"
        ],
        ComplianceRiskCategory.DISCRIMINATION: [
            r"\b(discriminate|discriminating|discrimination)\s+against",
            r"\b(racial|ethnic|religious|gender)\s+(discrimination|bias|prejudice)",
            r"\b(target|exclude)\s+based\s+on\s+(race|gender|religion|age|disability)"
        ],
        ComplianceRiskCategory.HARASSMENT: [
            r"\b(harass|threaten|intimidate|bully)",
            r"\b(sexual|verbal|physical)\s+harassment",
            r"\bhostile\s+(environment|workplace|behavior)"
        ],
        ComplianceRiskCategory.INAPPROPRIATE_CONTENT: [
            r"\b(explicit|obscene|pornographic)\s+(content|material|imagery)",
            r"\b(share|distribute|sell)\s+(adult|explicit)\s+content",
            r"\b(sexualized|violent)\s+content"
        ],
        ComplianceRiskCategory.OTHER: [
            r"\b(bribe|corruption|kickback)",
            r"\binsider\s+trading",
            r"\b(corporate|business)\s+espionage"
        ]
    }
    
    @classmethod
    def check_message_compliance(
        cls, 
        message_content: str,
        risk_patterns: Optional[Dict[ComplianceRiskCategory, List[str]]] = None
    ) -> Tuple[bool, Optional[ComplianceRiskCategory], List[str]]:
        """
        Analyze a message for compliance risks.
        
        Args:
            message_content: The message text to analyze
            risk_patterns: Optional custom risk patterns to use instead of defaults
            
        Returns:
            Tuple of (is_compliant, risk_category, detected_phrases)
        """
        patterns = risk_patterns or cls.DEFAULT_RISK_PATTERNS
        
        # Normalize text for better matching
        normalized_text = message_content.lower()
        
        for category, pattern_list in patterns.items():
            detected_phrases = []
            
            for pattern in pattern_list:
                matches = re.finditer(pattern, normalized_text, re.IGNORECASE)
                for match in matches:
                    detected_phrases.append(match.group(0))
            
            if detected_phrases:
                # Found risky content
                return False, category, detected_phrases
        
        # No risks detected
        return True, None, []
    
    @classmethod
    def log_compliance_issue(
        cls,
        lead: Lead,
        message_content: str,
        conversation_id: Optional[int],
        risk_category: ComplianceRiskCategory,
        detected_phrases: List[str],
        action_taken: str,
        db: Session
    ) -> ComplianceLog:
        """
        Log a compliance issue to the database.
        
        Args:
            lead: The lead involved
            message_content: The message content
            conversation_id: ID of the conversation (if available)
            risk_category: The type of risk detected
            detected_phrases: List of phrases that triggered the detection
            action_taken: Action taken in response
            db: Database session
            
        Returns:
            The created ComplianceLog entry
        """
        try:
            log_entry = ComplianceLog(
                lead_id=lead.id,
                conversation_id=conversation_id,
                risk_category=risk_category,
                message_content=message_content,
                detected_phrases=detected_phrases,
                action_taken=action_taken,
                created_at=datetime.utcnow()
            )
            
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            
            logger.warning(
                f"Compliance issue detected - Lead: {lead.email}, "
                f"Category: {risk_category}, Action: {action_taken}"
            )
            
            return log_entry
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error logging compliance issue: {str(e)}")
            raise
    
    @classmethod
    def handle_compliance_issue(
        cls,
        lead: Lead,
        message_content: str,
        conversation_id: Optional[int],
        risk_category: ComplianceRiskCategory,
        detected_phrases: List[str],
        db: Session
    ) -> Dict[str, Any]:
        """
        Handle a detected compliance issue.
        
        Args:
            lead: The lead involved
            message_content: The message content
            conversation_id: ID of the conversation (if available)
            risk_category: The type of risk detected
            detected_phrases: List of phrases that triggered the detection
            db: Database session
            
        Returns:
            Dictionary with handling results
        """
        try:
            # 1. Log the compliance issue
            log_entry = cls.log_compliance_issue(
                lead=lead,
                message_content=message_content,
                conversation_id=conversation_id,
                risk_category=risk_category,
                detected_phrases=detected_phrases,
                action_taken="escalated_to_human",
                db=db
            )
            
            # 2. Generate appropriate response based on risk category
            response_message = cls.get_compliance_response(risk_category)
            
            # 3. Send the response to the lead
            messaging_result = MessagingService.send_message(lead, response_message)
            
            # 4. Create a notification for human review
            from ..services.notification import NotificationService
            
            notification_content = (
                f"COMPLIANCE ALERT: Risk detected in conversation with {lead.full_name} ({lead.email})\n"
                f"Risk Category: {risk_category}\n"
                f"Detected Phrases: {', '.join(detected_phrases)}\n"
                f"Original Message: {message_content}\n"
                f"Automatic Response: {response_message}"
            )
            
            NotificationService.create_notification(
                lead_id=lead.id,
                notification_type="compliance_escalation",
                content=notification_content,
                db=db,
                priority=3  # High priority
            )
            
            return {
                "success": True,
                "is_compliant": False,
                "risk_category": risk_category,
                "detected_phrases": detected_phrases,
                "response_message": response_message,
                "log_entry_id": log_entry.id,
                "messaging_result": messaging_result
            }
            
        except Exception as e:
            logger.error(f"Error handling compliance issue: {str(e)}")
            return {
                "success": False,
                "is_compliant": False,
                "risk_category": risk_category,
                "error": str(e)
            }
    
    @classmethod
    def get_compliance_response(cls, risk_category: ComplianceRiskCategory) -> str:
        """
        Get an appropriate response message for a compliance issue.
        
        Args:
            risk_category: The type of risk detected
            
        Returns:
            Response message to send to the lead
        """
        # General response template
        general_response = (
            "I apologize, but I'm unable to discuss this topic as it may violate our company's "
            "compliance policies. I'll connect you with a human representative who can better "
            "assist you with your inquiry. They will contact you shortly."
        )
        
        # Category-specific responses
        category_responses = {
            ComplianceRiskCategory.ILLEGAL_ACTIVITY: (
                "I apologize, but I cannot assist with activities that may be illegal or violate regulations. "
                "I'll connect you with a human representative who can clarify what services we can legally provide. "
                "They will contact you shortly."
            ),
            ComplianceRiskCategory.PRIVACY_VIOLATION: (
                "I apologize, but I cannot assist with activities that may violate privacy rights or data protection laws. "
                "I'll connect you with a human representative who can discuss our privacy-compliant services. "
                "They will contact you shortly."
            ),
            ComplianceRiskCategory.FINANCIAL_FRAUD: (
                "I apologize, but I cannot assist with activities that may involve financial fraud or deception. "
                "I'll connect you with a human representative who can discuss our legitimate financial services. "
                "They will contact you shortly."
            )
        }
        
        # Return category-specific response if available, otherwise general response
        return category_responses.get(risk_category, general_response) 