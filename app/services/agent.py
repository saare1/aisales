import logging
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import re
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Lead, LeadStatus, ConversationChannel
from app.db.database import get_db_session
from app.services.memory import MemoryManager
from app.services.messaging import MessagingService
from app.services.scheduler import SchedulerService
from app.services.sentiment_analyzer import SentimentAnalyzer
from app.services.message_queue import MessageQueue, global_message_queue
from app.services.playbook_manager import PlaybookManager
from app.services.report_generator import ReportGenerator, ReportType, ReportFormat
from app.services.product_recommendation import ProductRecommendationEngine
from app.services.compliance_guardrails import ComplianceGuardrails

# Configure logging
logger = logging.getLogger(__name__)

# Try to import OpenAI if available
try:
    import openai
except ImportError:
    openai = None


class SalesAgentException(Exception):
    """Exception raised by the Sales Agent."""
    pass


class SalesCloserAgent:
    """
    Main AI Sales Closer Agent that handles conversations with leads.
    """
    
    def __init__(self, openai_api_key: Optional[str] = None):
        """
        Initialize the Sales Closer Agent.
        
        Args:
            openai_api_key: OpenAI API key (defaults to settings.OPENAI_API_KEY)
        """
        # Use provided API key or fall back to settings
        self.openai_api_key = openai_api_key or settings.OPENAI_API_KEY
        
        # Set up OpenAI client if available
        if openai and self.openai_api_key:
            openai.api_key = self.openai_api_key
    
    def _get_system_prompt(self, lead_context: Dict[str, Any]) -> str:
        """
        Generate the system prompt for the OpenAI model, now with playbook customization.
        
        Args:
            lead_context: Context information about the lead
            
        Returns:
            System prompt string
        """
        base_prompt = f"""
You are an AI Sales Closer Agent for a business. Your goal is to convert warm leads into paying customers.

About the business:
- Business type: Small business/solopreneur
- Key selling points: Personalized service, expertise, proven results

About the lead:
- Name: {lead_context.get("name", "Unknown")}
- Email: {lead_context.get("email", "Unknown")}
- Company: {lead_context.get("company", "Unknown")}
- Job Title: {lead_context.get("job_title", "Unknown")}
- Source: {lead_context.get("source", "Unknown")}
- Current Status: {lead_context.get("status", "new")}
- Needs: {lead_context.get("needs", "Unknown")}
- Budget: {lead_context.get("budget", "Unknown")}
- Objections: {lead_context.get("objections", "Unknown")}

Sales Approach:
1. Be friendly, confident, and professional at all times
2. Personalize your responses based on the lead's information
3. Ask qualifying questions to understand needs and budget if not already known
4. Address objections with empathy and evidence
5. Recognize buying signals and move toward closing when appropriate
6. Suggest appropriate next steps based on the lead's status
7. Vary your phrasing to sound natural and human
8. When appropriate, recommend products that match the lead's needs

Conversation History:
{lead_context.get("conversation_history", "No previous conversation")}

Your personality:
- Friendly but professional
- Confident but not pushy
- Helpful and solution-oriented
- Calm when handling objections
- Persuasive without being aggressive

When leading a conversation:
- Always address the lead by name when possible
- Ask open-ended questions to keep the conversation going
- Look for opportunities to highlight value and benefits
- Move the lead toward a specific action (booking a call, requesting a quote, etc.)
- If the lead seems confused or frustrated, apologize and offer to connect them with a human
- When the lead expresses specific needs, recommend relevant products

Products and Offers:
- You can recommend personalized products based on the lead's needs and preferences
- To recommend a product, use the action [ACTION:RECOMMEND_PRODUCT|product_id=ID]
- Only recommend products when you have a good understanding of the lead's needs
- Include the recommendation naturally in the conversation flow

Do not:
- Use excessive sales language or jargon
- Make unrealistic promises
- Push too hard when the lead clearly isn't ready
- Continue pursuing a lead who explicitly says they're not interested
- Recommend products that don't align with the lead's expressed needs

Always be ready to:
- Schedule meetings using a calendar link
- Send additional information when requested
- Escalate to a human when necessary
- Recommend relevant products with explanations of their benefits
"""

        # Get lead sentiment information if available
        sentiment_info = ""
        if lead_context.get("sentiment_score") is not None:
            sentiment_score = lead_context.get("sentiment_score")
            sentiment_category = "positive" if sentiment_score > 0.05 else ("negative" if sentiment_score < -0.05 else "neutral")
            sentiment_trend = lead_context.get("sentiment_trend", "unknown")
            
            sentiment_info = f"""
Lead Sentiment Analysis:
- Current sentiment: {sentiment_category.title()} (score: {sentiment_score:.2f})
- Sentiment trend: {sentiment_trend.title()}

Adjust your tone accordingly:
- For positive sentiment: Be enthusiastic and build on their excitement
- For negative sentiment: Be empathetic and focus on addressing concerns
- For neutral sentiment: Be balanced and informative
"""
            base_prompt += sentiment_info
        
        # Get the lead object to apply playbook
        lead_id = lead_context.get("lead_id")
        if lead_id:
            try:
                db = get_db_session()
                lead = db.query(Lead).filter(Lead.id == lead_id).first()
                if lead:
                    # Get the appropriate playbook
                    playbook = PlaybookManager.get_playbook(lead, db)
                    # Apply playbook customizations to the prompt
                    return PlaybookManager.apply_playbook_to_system_prompt(base_prompt, playbook, lead_context)
            except Exception as e:
                logger.error(f"Error applying playbook: {str(e)}")
            finally:
                db.close()
        
        return base_prompt
    
    def _parse_response_for_actions(self, response_text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Parse the AI response text for any embedded actions.
        
        Actions are embedded in the format: [ACTION:type|param1=value1|param2=value2]
        
        Args:
            response_text: The AI's response text
            
        Returns:
            Tuple of (cleaned message text, list of action dictionaries)
        """
        # Look for action patterns
        action_pattern = r'\[ACTION:(.*?)\]'
        actions = []
        
        # Find all actions
        for match in re.finditer(action_pattern, response_text):
            action_str = match.group(1)
            
            # Split into action type and parameters
            parts = action_str.split('|')
            if not parts:
                continue
                
            action_type = parts[0].strip()
            action_params = {}
            
            # Parse parameters
            for part in parts[1:]:
                if '=' in part:
                    key, value = part.split('=', 1)
                    action_params[key.strip()] = value.strip()
            
            # Add the action
            actions.append({
                "type": action_type,
                "params": action_params
            })
        
        # Remove action tags from the response
        cleaned_text = re.sub(action_pattern, '', response_text)
        
        return cleaned_text, actions
    
    def _execute_actions(
        self, 
        actions: List[Dict[str, Any]],
        lead: Lead,
        db: Session
    ) -> List[Dict[str, Any]]:
        """
        Execute the actions identified in the AI's response.
        
        Args:
            actions: List of actions to execute
            lead: The lead in context
            db: Database session
            
        Returns:
            List of action execution results
        """
        results = []
        scheduler = SchedulerService(db)
        
        for action in actions:
            action_type = action.get("type")
            params = action.get("params", {})
            
            if action_type == "SCHEDULE_MEETING":
                # Schedule a meeting
                try:
                    time_str = params.get("time", "")
                    notes = params.get("notes", "")
                    duration = params.get("duration", 30)
                    
                    # If no time was provided, schedule for default time
                    if not time_str:
                        time_str = "tomorrow at 10:00 AM"
                    
                    meeting_result = scheduler.schedule_meeting(
                        lead_id=lead.id,
                        scheduled_time=time_str,
                        duration_minutes=duration,
                        notes=notes
                    )
                    
                    results.append({
                        "action": "SCHEDULE_MEETING",
                        "success": True,
                        "details": meeting_result
                    })
                except Exception as e:
                    results.append({
                        "action": "SCHEDULE_MEETING",
                        "success": False,
                        "error": str(e)
                    })
            
            elif action_type == "SCHEDULE_FOLLOWUP":
                # Schedule a follow-up
                try:
                    time_str = params.get("time", "")
                    message = params.get("message", "")
                    
                    # If no time was provided, schedule for tomorrow
                    if not time_str:
                        time_str = "tomorrow at 10:00 AM"
                    
                    followup_result = scheduler.schedule_followup(
                        lead_id=lead.id,
                        scheduled_time=time_str,
                        message=message
                    )
                    
                    results.append({
                        "action": "SCHEDULE_FOLLOWUP",
                        "success": True,
                        "details": followup_result
                    })
                except Exception as e:
                    results.append({
                        "action": "SCHEDULE_FOLLOWUP",
                        "success": False,
                        "error": str(e)
                    })
            
            elif action_type == "SEND_INFORMATION":
                # Send information
                try:
                    info_type = params.get("type", "")
                    # In a real implementation, this would send actual information
                    results.append({
                        "action": "SEND_INFORMATION",
                        "success": True,
                        "details": {
                            "lead_id": lead.id,
                            "info_type": info_type
                        }
                    })
                except Exception as e:
                    results.append({
                        "action": "SEND_INFORMATION",
                        "success": False,
                        "error": str(e)
                    })
            
            elif action_type == "UPDATE_LEAD":
                # Update lead information
                try:
                    updates = {}
                    
                    # Process each possible update field
                    if "status" in params:
                        try:
                            updates["status"] = LeadStatus(params["status"])
                        except ValueError:
                            # Invalid status, ignore
                            pass
                    
                    for field in ["budget", "needs", "objections", "notes"]:
                        if field in params:
                            updates[field] = params[field]
                    
                    # Apply the updates
                    if updates:
                        MemoryManager.update_lead_info(lead.id, updates, db)
                        
                        results.append({
                            "action": "UPDATE_LEAD",
                            "success": True,
                            "details": {
                                "lead_id": lead.id,
                                "updates": updates
                            }
                        })
                except Exception as e:
                    results.append({
                        "action": "UPDATE_LEAD",
                        "success": False,
                        "error": str(e)
                    })
            
            elif action_type == "ESCALATE_TO_HUMAN":
                # Escalate to a human
                # In a real implementation, this would notify a human agent
                results.append({
                    "action": "ESCALATE_TO_HUMAN",
                    "success": True,
                    "details": {
                        "lead_id": lead.id,
                        "reason": params.get("reason", "Lead requested human assistance")
                    }
                })
                
            elif action_type == "RECOMMEND_PRODUCT":
                # Recommend a product to the lead
                try:
                    product_id = params.get("product_id")
                    
                    if not product_id:
                        # If no product_id was specified, generate recommendations
                        recommendation_engine = ProductRecommendationEngine(db, self.openai_api_key)
                        recommendations = recommendation_engine.generate_recommendations(lead.id)
                        
                        results.append({
                            "action": "RECOMMEND_PRODUCT",
                            "success": True,
                            "details": {
                                "lead_id": lead.id,
                                "generated_recommendations": recommendations
                            }
                        })
                    else:
                        # Product ID was provided, mark it as recommended
                        recommendation_engine = ProductRecommendationEngine(db, self.openai_api_key)
                        
                        # Check if this recommendation already exists
                        existing_recommendations = recommendation_engine.get_lead_recommendations(lead.id)
                        product_already_recommended = any(
                            rec.get("product_id") == product_id for rec in existing_recommendations
                        )
                        
                        if not product_already_recommended:
                            # Create a new recommendation with minimal data
                            # The full data will be populated next time recommendations are generated
                            recommendations_data = {
                                "recommendations": [
                                    {
                                        "product_id": product_id,
                                        "confidence_score": 0.7,  # Default confidence
                                        "reasons": ["Recommended by sales agent"]
                                    }
                                ]
                            }
                            recommendation_engine._save_recommendations(lead.id, recommendations_data)
                        
                        results.append({
                            "action": "RECOMMEND_PRODUCT",
                            "success": True,
                            "details": {
                                "lead_id": lead.id,
                                "product_id": product_id
                            }
                        })
                        
                except Exception as e:
                    results.append({
                        "action": "RECOMMEND_PRODUCT",
                        "success": False,
                        "error": str(e)
                    })
        
        return results
    
    def handle_message(
        self,
        lead_email: str,
        message_content: str,
        channel: ConversationChannel,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Handle an incoming message from a lead, now with sentiment analysis,
        message queue integration, and compliance guardrails.
        
        Args:
            lead_email: Email of the lead
            message_content: Content of the message
            channel: Channel through which the message was received
            db: Database session
            
        Returns:
            Dictionary with response and any actions taken
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = MemoryManager.get_lead_by_email(lead_email, db)
            if not lead:
                raise SalesAgentException(f"Lead with email {lead_email} not found")
            
            # Process the message through the message queue
            message_id = MessageQueue.process_incoming_message(
                global_message_queue,
                lead_email,
                message_content,
                channel,
                db
            )
            
            if not message_id:
                logger.error(f"Failed to process message from {lead_email}")
                raise SalesAgentException("Failed to process message")
            
            # Get the message
            message = db.query(Conversation).filter(Conversation.id == message_id).first()
            
            # NEW: Check message for compliance issues
            is_compliant, risk_category, detected_phrases = ComplianceGuardrails.check_message_compliance(
                message_content
            )
            
            # If compliance issue detected, handle it appropriately
            if not is_compliant:
                compliance_result = ComplianceGuardrails.handle_compliance_issue(
                    lead=lead,
                    message_content=message_content,
                    conversation_id=message_id,
                    risk_category=risk_category,
                    detected_phrases=detected_phrases,
                    db=db
                )
                
                # Store the incoming message
                MemoryManager.add_message(lead.id, message_content, True, channel, db)
                
                # Store the compliance response
                response_message = compliance_result.get("response_message", "")
                MemoryManager.add_message(lead.id, response_message, False, channel, db)
                
                return {
                    "success": True,
                    "compliance_issue": True,
                    "response": response_message,
                    "risk_category": risk_category,
                    "detected_phrases": detected_phrases,
                    "escalated": True
                }
            
            # Continue normal processing for compliant messages
            # Analyze sentiment
            sentiment = SentimentAnalyzer.analyze_and_store_sentiment(message_id, message_content, db)
            sentiment_category = sentiment.get("category", "neutral")
            
            # Store the incoming message
            MemoryManager.add_message(lead.id, message_content, True, channel, db)
            
            # Get lead context, including sentiment information
            lead_context = MemoryManager.get_lead_context(lead.id, db)
            
            # Add sentiment information to the context
            lead_sentiment_history = SentimentAnalyzer.get_lead_sentiment_history(lead.id, limit=5, db=db)
            lead_overall_sentiment = SentimentAnalyzer.get_lead_overall_sentiment(lead.id, days=30, db=db)
            
            lead_context["sentiment_score"] = sentiment.get("compound", 0)
            lead_context["sentiment_category"] = sentiment_category
            lead_context["sentiment_history"] = lead_sentiment_history
            lead_context["sentiment_trend"] = lead_overall_sentiment.get("sentiment_trend", "stable")
            
            # Generate the system prompt
            system_prompt = self._get_system_prompt(lead_context)
            
            # Generate the user message
            user_message = f"The lead ({lead.full_name}) has sent the following message: {message_content}"
            
            # Generate a response using OpenAI
            if openai and self.openai_api_key:
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4",  # Using GPT-4 for best quality
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7,  # Slightly creative but mostly consistent
                        max_tokens=500,  # Reasonable length for a sales message
                    )
                    
                    # Extract the response text
                    response_text = response.choices[0].message.content
                except Exception as e:
                    logger.error(f"OpenAI API error: {str(e)}")
                    response_text = "I apologize, but I'm having trouble processing your request. Let me connect you with a human representative who can assist you further."
            else:
                # If OpenAI is not available, use a fallback response
                response_text = f"Hello {lead.first_name}, thank you for your message. A member of our team will get back to you shortly."
            
            # Parse response for actions
            cleaned_response, actions = self._parse_response_for_actions(response_text)
            
            # Modify the response based on sentiment
            cleaned_response = SentimentAnalyzer.modify_response_for_sentiment(
                cleaned_response, 
                sentiment_category
            )
            
            # Store the agent's response
            MemoryManager.add_message(lead.id, cleaned_response, False, channel, db)
            
            # Execute any actions
            action_results = self._execute_actions(actions, lead, db)
            
            # Send the response through the appropriate channel
            messaging_result = MessagingService.send_message(lead, cleaned_response)
            
            return {
                "success": True,
                "response": cleaned_response,
                "actions": action_results,
                "messaging_result": messaging_result,
                "sentiment": sentiment
            }
        finally:
            if close_db:
                db.close()
    
    def greet_lead(
        self,
        lead: Lead,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Generate and send an initial greeting to a new lead, now using playbooks.
        
        Args:
            lead: The lead to greet
            db: Database session
            
        Returns:
            Dictionary with greeting response and any actions taken
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get lead context
            lead_context = MemoryManager.get_lead_context(lead.id, db)
            
            # Get the appropriate playbook
            playbook = PlaybookManager.get_playbook(lead, db)
            
            # Try to use a templated greeting from the playbook
            try:
                templated_greeting = PlaybookManager.get_templated_message(
                    playbook, 
                    "greeting", 
                    lead_context
                )
                
                # Use the templated greeting if one was generated
                if templated_greeting:
                    greeting_text = templated_greeting
                    
                    # Parse for actions and store the greeting
                    cleaned_greeting, actions = self._parse_response_for_actions(greeting_text)
                    MemoryManager.add_message(lead.id, cleaned_greeting, False, lead.preferred_channel, db)
                    
                    # Execute actions and send message
                    action_results = self._execute_actions(actions, lead, db)
                    messaging_result = MessagingService.send_message(lead, cleaned_greeting)
                    
                    return {
                        "success": True,
                        "greeting": cleaned_greeting,
                        "actions": action_results,
                        "messaging_result": messaging_result,
                        "templated": True
                    }
            except Exception as e:
                logger.error(f"Error using templated greeting: {str(e)}")
                # Fall back to AI-generated greeting below
            
            # Generate the system prompt
            system_prompt = self._get_system_prompt(lead_context)
            
            # Generate the user message
            user_message = f"This is a new lead ({lead.full_name}) from {lead.source or 'unknown source'}. Generate a friendly, personalized greeting that introduces yourself as an AI sales agent and asks an appropriate qualifying question."
            
            # Generate a greeting using OpenAI
            if openai and self.openai_api_key:
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7,
                        max_tokens=300,
                    )
                    
                    # Extract the response text
                    greeting_text = response.choices[0].message.content
                except Exception as e:
                    logger.error(f"OpenAI API error: {str(e)}")
                    greeting_text = f"Hello {lead.first_name}, thank you for your interest! How can I assist you today?"
            else:
                # If OpenAI is not available, use a fallback greeting
                greeting_text = f"Hello {lead.first_name}, thank you for your interest! How can I assist you today?"
            
            # Parse response for actions
            cleaned_greeting, actions = self._parse_response_for_actions(greeting_text)
            
            # Store the agent's greeting
            MemoryManager.add_message(lead.id, cleaned_greeting, False, lead.preferred_channel, db)
            
            # Execute any actions
            action_results = self._execute_actions(actions, lead, db)
            
            # Send the greeting through the appropriate channel
            messaging_result = MessagingService.send_message(lead, cleaned_greeting)
            
            return {
                "success": True,
                "greeting": cleaned_greeting,
                "actions": action_results,
                "messaging_result": messaging_result,
                "templated": False
            }
        finally:
            if close_db:
                db.close()
    
    def handle_objection(
        self,
        lead_id: int,
        objection_type: str,
        objection_content: str,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Generate a response to handle a specific objection from a lead.
        
        Args:
            lead_id: ID of the lead
            objection_type: Type of objection (e.g., "price", "timing", "competition")
            objection_content: Content of the objection
            db: Database session
            
        Returns:
            Dictionary with response and any actions taken
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                raise SalesAgentException(f"Lead with ID {lead_id} not found")
            
            # Get lead context
            lead_context = MemoryManager.get_lead_context(lead_id, db)
            
            # Generate the system prompt
            system_prompt = self._get_system_prompt(lead_context)
            
            # Generate the user message
            user_message = f"The lead ({lead.full_name}) has raised an objection of type '{objection_type}'. Here's what they said: '{objection_content}'. Generate a response that addresses this objection empathetically and persuasively."
            
            # Generate a response using OpenAI
            if openai and self.openai_api_key:
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7,
                        max_tokens=400,
                    )
                    
                    # Extract the response text
                    response_text = response.choices[0].message.content
                except Exception as e:
                    logger.error(f"OpenAI API error: {str(e)}")
                    response_text = f"I understand your concern about {objection_type}, {lead.first_name}. Let me address that..."
            else:
                # If OpenAI is not available, use a fallback response
                response_text = f"I understand your concern about {objection_type}, {lead.first_name}. Let me address that..."
            
            # Parse response for actions
            cleaned_response, actions = self._parse_response_for_actions(response_text)
            
            # Store the agent's response
            MemoryManager.add_message(lead.id, cleaned_response, False, lead.preferred_channel, db)
            
            # Update lead's objections
            if lead.objections:
                lead.objections += f"\n{objection_type}: {objection_content}"
            else:
                lead.objections = f"{objection_type}: {objection_content}"
            db.commit()
            
            # Execute any actions
            action_results = self._execute_actions(actions, lead, db)
            
            # Send the response through the appropriate channel
            messaging_result = MessagingService.send_message(lead, cleaned_response)
            
            return {
                "success": True,
                "response": cleaned_response,
                "actions": action_results,
                "messaging_result": messaging_result
            }
        finally:
            if close_db:
                db.close()
    
    def follow_up_lead(
        self,
        lead_id: int,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Generate and send a follow-up message to a lead.
        
        Args:
            lead_id: ID of the lead
            db: Database session
            
        Returns:
            Dictionary with follow-up response and any actions taken
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                raise SalesAgentException(f"Lead with ID {lead_id} not found")
            
            # Check if we should follow up
            if not SchedulerService.should_schedule_followup(lead):
                return {
                    "success": False,
                    "reason": "Follow-up not needed or not appropriate at this time"
                }
            
            # Get lead context
            lead_context = MemoryManager.get_lead_context(lead_id, db)
            
            # Generate the system prompt
            system_prompt = self._get_system_prompt(lead_context)
            
            # Generate the user message
            user_message = f"Generate a follow-up message for the lead ({lead.full_name}) who hasn't responded in {lead_context.get('days_since_last_contact', '?')} days. This is follow-up #{lead.followup_count + 1}."
            
            # Generate a follow-up using OpenAI
            if openai and self.openai_api_key:
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7,
                        max_tokens=350,
                    )
                    
                    # Extract the response text
                    followup_text = response.choices[0].message.content
                except Exception as e:
                    logger.error(f"OpenAI API error: {str(e)}")
                    followup_text = f"Hello {lead.first_name}, I wanted to follow up on our previous conversation. Is there anything I can help with?"
            else:
                # If OpenAI is not available, use a fallback follow-up
                followup_text = f"Hello {lead.first_name}, I wanted to follow up on our previous conversation. Is there anything I can help with?"
            
            # Parse response for actions
            cleaned_followup, actions = self._parse_response_for_actions(followup_text)
            
            # Store the agent's follow-up
            MemoryManager.add_message(lead.id, cleaned_followup, False, lead.preferred_channel, db)
            
            # Increment the follow-up count
            MemoryManager.increment_followup_count(lead_id, db)
            
            # Execute any actions
            action_results = self._execute_actions(actions, lead, db)
            
            # Send the follow-up through the appropriate channel
            messaging_result = MessagingService.send_message(lead, cleaned_followup)
            
            return {
                "success": True,
                "followup": cleaned_followup,
                "actions": action_results,
                "messaging_result": messaging_result
            }
        finally:
            if close_db:
                db.close()
    
    def close_sale(
        self,
        lead_id: int,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Attempt to close the sale with a lead.
        
        Args:
            lead_id: ID of the lead
            db: Database session
            
        Returns:
            Dictionary with closing response and any actions taken
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                raise SalesAgentException(f"Lead with ID {lead_id} not found")
            
            # Get lead context
            lead_context = MemoryManager.get_lead_context(lead_id, db)
            
            # Generate the system prompt
            system_prompt = self._get_system_prompt(lead_context)
            
            # Generate the user message
            user_message = f"The lead ({lead.full_name}) is showing buying signals. Generate a closing message that summarizes the value proposition and provides a clear next step for purchase or commitment."
            
            # Generate a closing message using OpenAI
            if openai and self.openai_api_key:
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7,
                        max_tokens=500,
                    )
                    
                    # Extract the response text
                    closing_text = response.choices[0].message.content
                except Exception as e:
                    logger.error(f"OpenAI API error: {str(e)}")
                    closing_text = f"Thank you for your interest, {lead.first_name}. Would you like to proceed with the next steps?"
            else:
                # If OpenAI is not available, use a fallback closing
                closing_text = f"Thank you for your interest, {lead.first_name}. Would you like to proceed with the next steps?"
            
            # Parse response for actions
            cleaned_closing, actions = self._parse_response_for_actions(closing_text)
            
            # Store the agent's closing message
            MemoryManager.add_message(lead.id, cleaned_closing, False, lead.preferred_channel, db)
            
            # Update lead status to negotiating
            MemoryManager.update_lead_status(lead_id, LeadStatus.NEGOTIATING, db)
            
            # Execute any actions
            action_results = self._execute_actions(actions, lead, db)
            
            # Send the closing message through the appropriate channel
            messaging_result = MessagingService.send_message(lead, cleaned_closing)
            
            return {
                "success": True,
                "closing": cleaned_closing,
                "actions": action_results,
                "messaging_result": messaging_result
            }
        finally:
            if close_db:
                db.close()
    
    def process_message_queue(
        self,
        max_messages: int = 10,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Process pending messages from the message queue.
        
        Args:
            max_messages: Maximum number of messages to process
            db: Database session
            
        Returns:
            Dictionary with processing results
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            processed_count = 0
            results = []
            
            for _ in range(max_messages):
                # Get the next message from the queue
                message = global_message_queue.dequeue()
                if not message:
                    break
                
                try:
                    # Process the message
                    result = self.handle_message(
                        message.lead_email,
                        message.content,
                        message.channel,
                        db
                    )
                    
                    results.append({
                        "message_id": message.message_id,
                        "lead_email": message.lead_email,
                        "success": True,
                        "response": result.get("response", "")
                    })
                    
                    processed_count += 1
                except Exception as e:
                    logger.error(f"Error processing queued message: {str(e)}")
                    results.append({
                        "message_id": message.message_id,
                        "lead_email": message.lead_email,
                        "success": False,
                        "error": str(e)
                    })
            
            return {
                "success": True,
                "processed_count": processed_count,
                "queue_size": global_message_queue.size(),
                "results": results
            }
        finally:
            if close_db:
                db.close()
    
    def generate_daily_report(
        self,
        recipient_email: Optional[str] = None,
        include_lead_details: bool = False,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Generate and optionally send a daily sales activity report.
        
        Args:
            recipient_email: Email to send the report to (if provided)
            include_lead_details: Whether to include lead details
            db: Database session
            
        Returns:
            Dictionary with report generation results
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Generate the report
            report = ReportGenerator.generate_activity_report(
                report_type=ReportType.DAILY,
                include_lead_details=include_lead_details,
                format_type=ReportFormat.HTML if recipient_email else ReportFormat.JSON,
                db=db
            )
            
            # Send the report if recipient provided
            if recipient_email:
                result = ReportGenerator.send_report_email(
                    report_data=report,
                    recipient_email=recipient_email,
                    report_format=ReportFormat.HTML
                )
                
                return {
                    "success": True,
                    "report": report,
                    "email_sent": True,
                    "email_result": result
                }
            
            return {
                "success": True,
                "report": report,
                "email_sent": False
            }
        finally:
            if close_db:
                db.close()
    
    def generate_weekly_report(
        self,
        recipient_email: Optional[str] = None,
        include_lead_details: bool = True,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Generate and optionally send a weekly sales activity report.
        
        Args:
            recipient_email: Email to send the report to (if provided)
            include_lead_details: Whether to include lead details
            db: Database session
            
        Returns:
            Dictionary with report generation results
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Generate the report
            report = ReportGenerator.generate_activity_report(
                report_type=ReportType.WEEKLY,
                include_lead_details=include_lead_details,
                format_type=ReportFormat.HTML if recipient_email else ReportFormat.JSON,
                db=db
            )
            
            # Send the report if recipient provided
            if recipient_email:
                result = ReportGenerator.send_report_email(
                    report_data=report,
                    recipient_email=recipient_email,
                    report_format=ReportFormat.HTML
                )
                
                return {
                    "success": True,
                    "report": report,
                    "email_sent": True,
                    "email_result": result
                }
            
            return {
                "success": True,
                "report": report,
                "email_sent": False
            }
        finally:
            if close_db:
                db.close()
    
    def schedule_recurring_reports(
        self,
        email: str,
        daily_report_time: Optional[str] = None,
        weekly_report_time: Optional[str] = None,
        weekly_report_day: str = "Monday",
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Schedule recurring daily and/or weekly reports.
        
        Args:
            email: Email to send reports to
            daily_report_time: Time for daily reports (HH:MM)
            weekly_report_time: Time for weekly reports (HH:MM)
            weekly_report_day: Day for weekly reports
            db: Database session
            
        Returns:
            Dictionary with scheduling results
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            results = {}
            
            # Schedule daily report if time provided
            if daily_report_time:
                daily_result = ReportGenerator.schedule_recurring_reports(
                    report_type=ReportType.DAILY,
                    recipient_email=email,
                    schedule_time=daily_report_time,
                    include_lead_details=False,
                    db=db
                )
                results["daily_report"] = daily_result
            
            # Schedule weekly report if time provided
            if weekly_report_time:
                weekly_result = ReportGenerator.schedule_recurring_reports(
                    report_type=ReportType.WEEKLY,
                    recipient_email=email,
                    schedule_time=weekly_report_time,
                    include_lead_details=True,
                    db=db
                )
                results["weekly_report"] = weekly_result
            
            return {
                "success": True,
                "scheduled_reports": results
            }
        finally:
            if close_db:
                db.close()

# List of valid action types
VALID_ACTION_TYPES = [
    "SCHEDULE_MEETING", 
    "SCHEDULE_FOLLOWUP", 
    "SEND_INFORMATION",
    "UPDATE_LEAD",
    "ESCALATE_TO_HUMAN",
    "RECOMMEND_PRODUCT"
] 