import logging
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models import Lead, Conversation, BusinessConfiguration

# Configure logging
logger = logging.getLogger(__name__)


class PlaybookManager:
    """
    Service for managing conversation playbooks based on lead types and industries.
    A playbook defines the tone, style, question sequences, and messaging strategy
    to use with different types of leads.
    """
    
    # Default playbook templates if none defined in the database
    DEFAULT_PLAYBOOKS = {
        "default": {
            "name": "Default Playbook",
            "description": "Standard conversational approach for most leads",
            "tone": "friendly yet professional",
            "style": "consultative selling",
            "greeting_template": "Hello {lead_first_name}, thank you for your interest in our services. How can I assist you today?",
            "question_sequence": [
                "What specific challenges are you looking to solve?",
                "What is your timeline for implementing a solution?",
                "Have you set aside a budget for this project?",
                "Who else is involved in the decision-making process?"
            ],
            "objection_handling": {
                "price": "I understand budget is a concern. Our solutions are designed to provide significant ROI by {value_prop}.",
                "timing": "I understand timing is important. We can work with your schedule to ensure a smooth implementation.",
                "competition": "What I appreciate about {competitor} is {competitor_strength}. Where we differentiate is {differentiation}."
            },
            "closing_templates": [
                "Based on our conversation, I think the next step would be to schedule a demo. How does that sound?",
                "Given your needs, I'd recommend our {product_name} solution. Would you like to move forward with this option?",
                "Let's schedule a call with our team to discuss the specifics. Does that work for you?"
            ],
            "follow_up_templates": [
                "I wanted to follow up on our conversation about {topic}. Have you had a chance to consider our solution?",
                "Just checking in regarding our previous discussion. Is there any additional information I can provide?",
                "I'm reaching out to see if you have any questions about the proposal I sent over."
            ]
        },
        "technical": {
            "name": "Technical Lead Playbook",
            "description": "For technically-oriented leads who value specifications and details",
            "tone": "precise and data-driven",
            "style": "technical consultative",
            "greeting_template": "Hello {lead_first_name}, I understand you're exploring technical solutions in the {industry} space. I'd be happy to discuss specifics about our platform.",
            "question_sequence": [
                "What technical requirements are most important for your implementation?",
                "Are there specific integrations you need?",
                "What performance metrics are you looking to achieve?",
                "What is your current technical stack?"
            ],
            "objection_handling": {
                "technical_limitations": "Let me address that specific concern. Our system handles {limitation} by {solution}.",
                "complexity": "You're right to be concerned about complexity. Here's how we simplify the implementation process: {simplification}.",
                "scalability": "Regarding scalability, our platform has been proven to handle {scale_example} without performance degradation."
            },
            "closing_templates": [
                "Based on your technical requirements, I'd suggest scheduling a technical demo with one of our engineers. How does that sound?",
                "Would you like me to prepare a technical specification document based on what we've discussed?",
                "Our team can provide a proof of concept for your specific use case. Would that be valuable?"
            ]
        },
        "executive": {
            "name": "Executive Playbook",
            "description": "For C-suite and decision makers focused on business outcomes",
            "tone": "confident and business-focused",
            "style": "value-based selling",
            "greeting_template": "Hello {lead_first_name}, thank you for your interest. I'd like to understand how we can drive measurable business outcomes for {company}.",
            "question_sequence": [
                "What key business objectives are you looking to achieve?",
                "How are you measuring success for this initiative?",
                "What would be the impact of solving this challenge on your bottom line?",
                "When do you need to see results by?"
            ],
            "objection_handling": {
                "roi": "Our customers typically see ROI within {timeframe} through {benefit}.",
                "priority": "I understand you have many priorities. Our solution addresses your {key_objective} which you mentioned is critical to your annual goals.",
                "board_approval": "We can provide case studies and projected ROI analysis that will help make the case to your board."
            },
            "closing_templates": [
                "Based on the business outcomes you're seeking, I recommend moving forward with a solution proposal. I can have that to you by {date}.",
                "To achieve your Q{quarter} objectives, we should begin implementation by {date}. Would you like to proceed?",
                "I'm confident we can deliver the {percentage}% improvement you're targeting. Shall we discuss contract details?"
            ]
        },
        "small_business": {
            "name": "Small Business Playbook",
            "description": "For small business owners with limited resources",
            "tone": "helpful and straightforward",
            "style": "consultative with focus on efficiency",
            "greeting_template": "Hi {lead_first_name}, I appreciate small business owners like yourself taking the time to explore solutions. How can I help your business today?",
            "question_sequence": [
                "What specific business challenge are you trying to solve?",
                "How are you handling this currently?",
                "What would success look like for you?",
                "Are you the main decision maker for this purchase?"
            ],
            "objection_handling": {
                "price": "We have options designed specifically for small businesses like yours. Our {starter_plan} provides essential features while staying budget-friendly.",
                "implementation": "Our system is designed for quick setup, typically taking only {setup_time}. We also provide free onboarding assistance.",
                "too_complex": "We can start with the core features you need most, and you can add capabilities as your business grows."
            },
            "closing_templates": [
                "For small businesses like yours, I typically recommend starting with our {recommended_plan}. Does that align with your needs?",
                "We could have you up and running by {date}. Would you like me to help you get started?",
                "Many businesses your size find our monthly payment option helpful for cash flow. Would you prefer that to annual billing?"
            ]
        }
    }
    
    @classmethod
    def get_playbook(
        cls,
        lead: Lead,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Get the appropriate playbook for a lead based on their attributes.
        
        Args:
            lead: The lead to get a playbook for
            db: Database session
            
        Returns:
            Playbook dictionary with conversation strategy
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # First check if there's a custom playbook in the business configuration
            if lead.business_id:
                config = db.query(BusinessConfiguration).filter(
                    BusinessConfiguration.business_id == lead.business_id,
                    BusinessConfiguration.is_active == True
                ).first()
                
                if config and config.playbooks:
                    # Parse the JSON playbooks if stored as a string
                    playbooks = config.playbooks
                    if isinstance(playbooks, str):
                        try:
                            playbooks = json.loads(playbooks)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse playbooks JSON for business {lead.business_id}")
                            playbooks = {}
                    
                    # Try to find a matching playbook based on lead attributes
                    matched_playbook = cls._match_playbook_to_lead(lead, playbooks)
                    if matched_playbook:
                        logger.info(f"Using custom playbook '{matched_playbook.get('name')}' for lead {lead.id}")
                        return matched_playbook
            
            # Fall back to default playbooks if no custom playbook found
            matched_default = cls._match_playbook_to_lead(lead, cls.DEFAULT_PLAYBOOKS)
            
            logger.info(f"Using default playbook '{matched_default.get('name')}' for lead {lead.id}")
            return matched_default
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def _match_playbook_to_lead(lead: Lead, playbooks: Dict[str, Any]) -> Dict[str, Any]:
        """
        Match a lead to the most appropriate playbook.
        
        Args:
            lead: The lead to match
            playbooks: Dictionary of available playbooks
            
        Returns:
            The best matching playbook
        """
        # Start with default playbook as fallback
        best_match = playbooks.get("default", playbooks.get(next(iter(playbooks), {})))
        
        # Check for industry-specific playbook
        if hasattr(lead, "industry") and lead.industry:
            industry_playbook = playbooks.get(lead.industry.lower().replace(" ", "_"), None)
            if industry_playbook:
                return industry_playbook
        
        # Check for role-specific playbook
        if hasattr(lead, "job_title") and lead.job_title:
            job_title = lead.job_title.lower()
            
            # Match executive-level leads
            if any(title in job_title for title in ["ceo", "cto", "cfo", "coo", "chief", "director", "vp", "president", "founder", "owner"]):
                executive_playbook = playbooks.get("executive", None)
                if executive_playbook:
                    return executive_playbook
            
            # Match technical leads
            if any(title in job_title for title in ["developer", "engineer", "architect", "technical", "technology", "it ", "software", "data"]):
                technical_playbook = playbooks.get("technical", None)
                if technical_playbook:
                    return technical_playbook
        
        # Check for company size (if available)
        if hasattr(lead, "company_size") and lead.company_size:
            if lead.company_size.lower() in ["small", "1-10", "11-50"]:
                small_business_playbook = playbooks.get("small_business", None)
                if small_business_playbook:
                    return small_business_playbook
        
        return best_match
    
    @classmethod
    def apply_playbook_to_system_prompt(
        cls,
        base_system_prompt: str,
        playbook: Dict[str, Any],
        lead_context: Dict[str, Any]
    ) -> str:
        """
        Apply a playbook to the base system prompt to customize it for the lead.
        
        Args:
            base_system_prompt: The base system prompt
            playbook: The playbook to apply
            lead_context: Context information about the lead
            
        Returns:
            Customized system prompt
        """
        # Extract playbook attributes
        tone = playbook.get("tone", "friendly yet professional")
        style = playbook.get("style", "consultative selling")
        
        # Create playbook-specific additions to the prompt
        playbook_additions = f"""
This lead should be approached using the "{playbook.get('name', 'Default')}" playbook.

Communication style:
- Tone: {tone}
- Style: {style}
- Industry focus: {lead_context.get('industry', 'Unknown')}

When leading the conversation:
- Use terminology and examples relevant to {lead_context.get('industry', 'their industry')}
- Address the lead's specific concerns and goals
- Ask the most relevant questions to move the conversation forward
"""
        
        # Add question sequence if available
        question_sequence = playbook.get("question_sequence", [])
        if question_sequence:
            playbook_additions += "\nRecommended question sequence:\n"
            for i, question in enumerate(question_sequence, 1):
                playbook_additions += f"{i}. {question}\n"
        
        # Add objection handling guidance if available
        objection_handling = playbook.get("objection_handling", {})
        if objection_handling:
            playbook_additions += "\nWhen handling objections:\n"
            for objection_type, response in objection_handling.items():
                playbook_additions += f"- {objection_type.replace('_', ' ').title()}: {response}\n"
        
        # Insert the playbook additions after the "Your personality:" section
        if "Your personality:" in base_system_prompt:
            parts = base_system_prompt.split("Your personality:")
            customized_prompt = parts[0] + "Your personality:" + parts[1] + playbook_additions
        else:
            # If the section isn't found, add to the end
            customized_prompt = base_system_prompt + "\n" + playbook_additions
        
        return customized_prompt
    
    @classmethod
    def get_templated_message(
        cls,
        playbook: Dict[str, Any],
        template_type: str,
        lead_context: Dict[str, Any],
        index: int = 0
    ) -> str:
        """
        Get a templated message from the playbook and fill in the lead context.
        
        Args:
            playbook: The playbook to use
            template_type: Type of template (greeting, closing, follow_up)
            lead_context: Context information about the lead
            index: Index to use for template lists (for variety)
            
        Returns:
            Formatted template string
        """
        # Get the appropriate template
        if template_type == "greeting":
            template = playbook.get("greeting_template", "Hello {lead_first_name}, how can I help you today?")
        elif template_type == "closing":
            templates = playbook.get("closing_templates", ["Would you like to move forward with this solution?"])
            template = templates[index % len(templates)]
        elif template_type == "follow_up":
            templates = playbook.get("follow_up_templates", ["I'm following up on our previous conversation."])
            template = templates[index % len(templates)]
        else:
            # Default to a generic template
            template = "Hello {lead_first_name}, how can I assist you today?"
        
        # Replace template variables with lead context
        formatted = template
        
        # Get variables in the template (anything in {curly_braces})
        import re
        variables = re.findall(r'\{([^}]+)\}', template)
        
        # Replace each variable with its value from lead_context
        for var in variables:
            # Handle nested properties with dot notation (e.g., "company.name")
            if '.' in var:
                parts = var.split('.')
                value = lead_context
                for part in parts:
                    value = value.get(part, {}) if isinstance(value, dict) else {}
                replacement = str(value) if value else f"[{var}]"
            else:
                # Direct property
                replacement = str(lead_context.get(var, f"[{var}]"))
            
            formatted = formatted.replace(f"{{{var}}}", replacement)
        
        return formatted
    
    @classmethod
    def create_playbook(
        cls,
        name: str,
        description: str,
        business_id: Optional[int] = None,
        target_industries: Optional[List[str]] = None,
        target_roles: Optional[List[str]] = None,
        tone: str = "friendly yet professional",
        style: str = "consultative selling",
        greeting_template: Optional[str] = None,
        question_sequence: Optional[List[str]] = None,
        objection_handling: Optional[Dict[str, str]] = None,
        closing_templates: Optional[List[str]] = None,
        follow_up_templates: Optional[List[str]] = None,
        db: Session = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new playbook in the database.
        
        Args:
            name: Name of the playbook
            description: Description of the playbook
            business_id: Optional business ID for business-specific playbooks
            target_industries: List of industries this playbook targets
            target_roles: List of job roles this playbook targets
            tone: The tone to use for communication
            style: The selling style to use
            greeting_template: Template for greeting messages
            question_sequence: List of questions to ask in sequence
            objection_handling: Dictionary of objection types to responses
            closing_templates: List of templates for closing messages
            follow_up_templates: List of templates for follow-up messages
            db: Database session
            
        Returns:
            The created playbook if successful, None otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Create the playbook dictionary
            playbook_data = {
                "name": name,
                "description": description,
                "tone": tone,
                "style": style,
                "target_industries": target_industries or [],
                "target_roles": target_roles or [],
                "greeting_template": greeting_template or "Hello {lead_first_name}, how can I help you today?",
                "question_sequence": question_sequence or [],
                "objection_handling": objection_handling or {},
                "closing_templates": closing_templates or [],
                "follow_up_templates": follow_up_templates or [],
                "created_at": datetime.utcnow().isoformat()
            }
            
            # Save to the database
            if business_id:
                config = db.query(BusinessConfiguration).filter(
                    BusinessConfiguration.business_id == business_id
                ).first()
                
                if not config:
                    # Create a new configuration if none exists
                    config = BusinessConfiguration(
                        business_id=business_id,
                        is_active=True,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(config)
                
                # Add/update the playbook in the configuration
                playbooks = config.playbooks or {}
                if isinstance(playbooks, str):
                    try:
                        playbooks = json.loads(playbooks)
                    except json.JSONDecodeError:
                        playbooks = {}
                
                # Use a key based on target industries or name
                key = target_industries[0].lower().replace(" ", "_") if target_industries else name.lower().replace(" ", "_")
                playbooks[key] = playbook_data
                
                # Update the configuration
                config.playbooks = playbooks
                config.updated_at = datetime.utcnow()
                
                db.commit()
                
                logger.info(f"Created playbook '{name}' for business {business_id}")
                return playbook_data
            else:
                logger.warning("No business ID provided, playbook not saved to database")
                return playbook_data
        except Exception as e:
            if db:
                db.rollback()
            logger.error(f"Error creating playbook: {str(e)}")
            return None
        finally:
            if close_db and db:
                db.close() 