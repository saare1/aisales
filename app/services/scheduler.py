from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Lead, ScheduledAction, ConversationChannel, LeadStatus
from app.db.database import get_db_session
from app.services.messaging import MessagingService


class SchedulerService:
    """
    Service for scheduling and executing follow-up actions.
    
    In a production environment, this would be triggered by a cron job
    or a background worker process.
    """
    
    @staticmethod
    def schedule_followup(
        lead_id: int,
        content: str,
        scheduled_for: Optional[datetime] = None,
        channel: Optional[ConversationChannel] = None,
        db: Session = None
    ) -> ScheduledAction:
        """
        Schedule a follow-up message for a lead.
        
        Args:
            lead_id: The ID of the lead to follow up with
            content: The content of the follow-up message
            scheduled_for: When to send the follow-up (defaults to 24 hours from now)
            channel: The channel to use for the follow-up (defaults to lead's preferred channel)
            db: Database session
            
        Returns:
            The created ScheduledAction
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Default to 24 hours from now if not specified
            if scheduled_for is None:
                scheduled_for = datetime.utcnow() + timedelta(hours=settings.FOLLOWUP_INTERVAL_HOURS)
            
            # Get the lead to determine preferred channel if not specified
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                raise ValueError(f"Lead with ID {lead_id} not found")
            
            # Default to lead's preferred channel if not specified
            if channel is None:
                channel = lead.preferred_channel
            
            # Create the scheduled action
            action = ScheduledAction(
                lead_id=lead_id,
                action_type="followup",
                channel=channel,
                content=content,
                scheduled_for=scheduled_for,
                created_at=datetime.utcnow()
            )
            
            db.add(action)
            db.commit()
            db.refresh(action)
            
            return action
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def schedule_meeting(
        lead_id: int,
        meeting_time: datetime,
        duration_minutes: int = 30,
        meeting_type: str = "discovery",
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Schedule a meeting with a lead and send a calendar invitation.
        
        Args:
            lead_id: The ID of the lead to schedule with
            meeting_time: The time of the meeting
            duration_minutes: The duration of the meeting in minutes
            meeting_type: The type of meeting (discovery, demo, etc.)
            db: Database session
            
        Returns:
            A dictionary with information about the scheduled meeting
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                raise ValueError(f"Lead with ID {lead_id} not found")
            
            # Update lead status to reflect meeting scheduled
            lead.status = LeadStatus.MEETING_SCHEDULED
            db.commit()
            
            # Send calendar invitation
            result = MessagingService.send_calendar_invite(
                lead,
                meeting_time,
                duration_minutes,
                meeting_type
            )
            
            return {
                "success": True,
                "lead_id": lead_id,
                "meeting_time": meeting_time.isoformat(),
                "duration_minutes": duration_minutes,
                "meeting_type": meeting_type,
                "message_result": result
            }
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def get_pending_actions(db: Session = None) -> List[ScheduledAction]:
        """
        Get all pending actions that are due to be executed.
        
        Args:
            db: Database session
            
        Returns:
            A list of ScheduledAction objects
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            now = datetime.utcnow()
            
            return (
                db.query(ScheduledAction)
                .filter(
                    ScheduledAction.is_executed == False,
                    ScheduledAction.scheduled_for <= now
                )
                .all()
            )
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def execute_pending_actions(cls, db: Session = None) -> List[Dict[str, Any]]:
        """
        Execute all pending actions that are due.
        
        This method would typically be called by a cron job or background worker.
        
        Args:
            db: Database session
            
        Returns:
            A list of results from executed actions
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        results = []
        
        try:
            # Get pending actions
            actions = cls.get_pending_actions(db)
            
            for action in actions:
                try:
                    # Get the lead
                    lead = db.query(Lead).filter(Lead.id == action.lead_id).first()
                    if not lead:
                        continue
                    
                    # Execute the action based on type
                    if action.action_type == "followup":
                        # Send the follow-up message
                        result = MessagingService.send_message(
                            lead,
                            action.content,
                            "Following up on your inquiry"
                        )
                        
                        # Increment follow-up count
                        lead.followup_count += 1
                        
                        # Mark the action as executed
                        action.is_executed = True
                        action.executed_at = datetime.utcnow()
                        
                        # Add to results
                        results.append({
                            "action_id": action.id,
                            "action_type": action.action_type,
                            "lead_id": lead.id,
                            "lead_email": lead.email,
                            "result": result
                        })
                    
                    # Add other action types here as needed
                
                except Exception as e:
                    # Log the error but continue with other actions
                    import logging
                    logging.error(f"Error executing action {action.id}: {str(e)}")
            
            # Commit all changes
            db.commit()
            
            return results
        finally:
            if close_db:
                db.close()
    
    @staticmethod
    def should_schedule_followup(lead: Lead) -> bool:
        """
        Determine if a follow-up should be scheduled for a lead.
        
        Args:
            lead: The lead to check
            
        Returns:
            True if a follow-up should be scheduled, False otherwise
        """
        # Don't follow up if lead is inactive
        if not lead.is_active:
            return False
        
        # Don't follow up if we've reached the maximum number of follow-ups
        if lead.followup_count >= settings.MAX_FOLLOWUPS:
            return False
        
        # Don't follow up if lead has won or lost status
        if lead.status in [LeadStatus.WON, LeadStatus.LOST]:
            return False
        
        # Don't follow up if lead was contacted in the last 24 hours
        if lead.last_contact:
            time_since_contact = datetime.utcnow() - lead.last_contact
            if time_since_contact < timedelta(hours=settings.FOLLOWUP_INTERVAL_HOURS):
                return False
        
        # If we get here, a follow-up should be scheduled
        return True 