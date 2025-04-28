import logging
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.config import settings
from app.db.models import ConversationChannel, Lead

# Configure logging
logger = logging.getLogger(__name__)


class MessagingService:
    """
    Service for sending messages through various channels (email, SMS, etc.)
    
    Note: This is a mock implementation. In a production environment, this would 
    integrate with actual services like SendGrid, Twilio, etc.
    """
    
    @staticmethod
    def send_email(
        to_email: str,
        subject: str,
        content: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Mock implementation of sending an email.
        
        In a real implementation, this would use SendGrid, Mailgun, etc.
        """
        from_email = from_email or settings.EMAIL_FROM
        from_name = from_name or settings.EMAIL_NAME
        
        if not from_email:
            logger.warning("No sender email configured. Check your .env file.")
            return {"success": False, "error": "No sender email configured"}
        
        # Log the email sending (in production, this would actually send an email)
        logger.info(f"EMAIL SENT: To: {to_email}, Subject: {subject}, From: {from_name} <{from_email}>")
        logger.info(f"EMAIL CONTENT: {content}")
        
        # In a real implementation, this would return the response from the email API
        return {
            "success": True,
            "channel": ConversationChannel.EMAIL,
            "to": to_email,
            "subject": subject,
            "content": content,
            "sent_at": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    def send_sms(
        to_phone: str,
        content: str,
        from_phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Mock implementation of sending an SMS.
        
        In a real implementation, this would use Twilio or a similar service.
        """
        from_phone = from_phone or settings.TWILIO_PHONE_NUMBER
        
        if not from_phone:
            logger.warning("No sender phone number configured. Check your .env file.")
            return {"success": False, "error": "No sender phone number configured"}
        
        # Log the SMS sending (in production, this would actually send an SMS)
        logger.info(f"SMS SENT: To: {to_phone}, From: {from_phone}")
        logger.info(f"SMS CONTENT: {content}")
        
        # In a real implementation, this would return the response from the SMS API
        return {
            "success": True,
            "channel": ConversationChannel.SMS,
            "to": to_phone,
            "content": content,
            "sent_at": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    def send_chat_message(
        conversation_id: str,
        content: str
    ) -> Dict[str, Any]:
        """
        Mock implementation of sending a chat message.
        
        In a real implementation, this would use WebSockets or a chat API.
        """
        # Log the chat sending (in production, this would actually send a chat)
        logger.info(f"CHAT SENT: To conversation: {conversation_id}")
        logger.info(f"CHAT CONTENT: {content}")
        
        # In a real implementation, this would return the response from the chat API
        return {
            "success": True,
            "channel": ConversationChannel.CHAT,
            "conversation_id": conversation_id,
            "content": content,
            "sent_at": datetime.utcnow().isoformat()
        }
    
    @classmethod
    def send_message(
        cls,
        lead: Lead,
        content: str,
        subject: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a message to a lead through their preferred channel.
        
        Args:
            lead: The lead to send the message to
            content: The content of the message
            subject: The subject (for email only)
            
        Returns:
            A dictionary with information about the sent message
        """
        # Determine which channel to use
        channel = lead.preferred_channel
        
        # Set a default subject for emails if none is provided
        if channel == ConversationChannel.EMAIL and not subject:
            subject = f"Following up on your inquiry"
        
        # Send through the appropriate channel
        if channel == ConversationChannel.EMAIL:
            return cls.send_email(lead.email, subject, content)
        elif channel == ConversationChannel.SMS:
            if not lead.phone:
                logger.warning(f"No phone number for lead {lead.email}, falling back to email")
                return cls.send_email(lead.email, subject or "Following up on your inquiry", content)
            return cls.send_sms(lead.phone, content)
        elif channel == ConversationChannel.CHAT:
            # For chat, we'd use some kind of conversation ID, but for this mock we'll use email
            return cls.send_chat_message(lead.email, content)
        
        # If we get here, something went wrong
        logger.error(f"Unknown channel {channel} for lead {lead.email}")
        return {"success": False, "error": f"Unknown channel {channel}"}
    
    @classmethod
    def send_calendar_invite(
        cls,
        lead: Lead,
        meeting_time: datetime,
        duration_minutes: int = 30,
        meeting_type: str = "discovery"
    ) -> Dict[str, Any]:
        """
        Send a calendar invitation to a lead.
        
        Args:
            lead: The lead to send the invitation to
            meeting_time: The time of the meeting
            duration_minutes: The duration of the meeting in minutes
            meeting_type: The type of meeting (discovery, demo, etc.)
            
        Returns:
            A dictionary with information about the sent invitation
        """
        # In a real implementation, this would create a calendar event and send an invitation
        meeting_date_str = meeting_time.strftime("%A, %B %d at %I:%M %p")
        
        # Create the message content
        subject = f"Meeting Confirmation: {meeting_date_str}"
        content = f"""
Hi {lead.first_name},

I've scheduled a {duration_minutes}-minute {meeting_type} call with you for {meeting_date_str}.

You can add this to your calendar using the attached calendar invitation.

If you need to reschedule, please use this link: {settings.MEETING_LINK}

Looking forward to our conversation!

Best,
AI Sales Agent
"""
        
        # Send the message
        result = cls.send_email(lead.email, subject, content)
        
        # Add calendar invite information
        result["meeting_info"] = {
            "meeting_time": meeting_time.isoformat(),
            "duration_minutes": duration_minutes,
            "meeting_type": meeting_type
        }
        
        return result 