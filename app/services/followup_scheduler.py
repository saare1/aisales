import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models import Lead, FollowUp, FollowUpStatus, FollowUpPriority
from app.services.lead_scorer import LeadScorer

# Configure logging
logger = logging.getLogger(__name__)


class FollowUpScheduler:
    """
    Service for scheduling and managing follow-ups for leads.
    
    This service provides:
    1. Creation of follow-up tasks based on lead temperature and status
    2. Prioritization of follow-ups
    3. Retrieval of due follow-ups for processing
    """
    
    # Default follow-up intervals (in days) based on lead temperature
    DEFAULT_INTERVALS = {
        "hot": 1,       # Follow up with hot leads every day
        "warm": 3,      # Follow up with warm leads every 3 days
        "cool": 7,      # Follow up with cool leads every week
        "cold": 14      # Follow up with cold leads every 2 weeks
    }
    
    @classmethod
    def schedule_followup(
        cls,
        lead_id: int,
        due_date: Optional[datetime] = None,
        priority: Optional[FollowUpPriority] = None,
        notes: Optional[str] = None,
        db: Session = None
    ) -> Optional[int]:
        """
        Schedule a follow-up for a lead.
        
        Args:
            lead_id: The ID of the lead to follow up with
            due_date: The date and time when the follow-up should be done
            priority: The priority of the follow-up
            notes: Optional notes about the follow-up
            db: Database session
            
        Returns:
            ID of the created follow-up if successful, None otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the lead
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            
            if not lead:
                logger.error(f"Could not find lead with ID {lead_id}")
                return None
            
            # If due date not provided, calculate based on lead temperature
            if due_date is None:
                lead_scorer = LeadScorer()
                temperature = lead_scorer.determine_lead_temperature(lead.score)
                interval_days = cls.DEFAULT_INTERVALS.get(temperature.lower(), 7)
                due_date = datetime.utcnow() + timedelta(days=interval_days)
            
            # If priority not provided, calculate based on lead score
            if priority is None:
                priority = cls._calculate_priority(lead.score)
            
            # Create a new follow-up
            followup = FollowUp(
                lead_id=lead_id,
                created_at=datetime.utcnow(),
                due_date=due_date,
                status=FollowUpStatus.PENDING,
                priority=priority,
                notes=notes
            )
            
            db.add(followup)
            db.commit()
            
            logger.info(f"Scheduled follow-up for lead {lead_id} due on {due_date}")
            
            return followup.id
        except Exception as e:
            if db is not None:
                db.rollback()
            logger.error(f"Error scheduling follow-up: {str(e)}")
            return None
        finally:
            if close_db and db is not None:
                db.close()
    
    @classmethod
    def _calculate_priority(cls, lead_score: float) -> FollowUpPriority:
        """
        Calculate the priority of a follow-up based on lead score.
        
        Args:
            lead_score: The score of the lead
            
        Returns:
            The priority of the follow-up
        """
        if lead_score >= 80:
            return FollowUpPriority.HIGH
        elif lead_score >= 50:
            return FollowUpPriority.MEDIUM
        else:
            return FollowUpPriority.LOW
    
    @classmethod
    def get_due_followups(
        cls,
        user_id: Optional[int] = None,
        limit: int = 10,
        include_completed: bool = False,
        db: Session = None
    ) -> List[Dict[str, Any]]:
        """
        Get follow-ups that are due.
        
        Args:
            user_id: Optional ID of the user to get follow-ups for
            limit: The maximum number of follow-ups to return
            include_completed: Whether to include completed follow-ups
            db: Database session
            
        Returns:
            List of follow-ups that are due
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Query for follow-ups
            query = db.query(FollowUp, Lead).join(
                Lead, FollowUp.lead_id == Lead.id
            ).filter(
                FollowUp.due_date <= datetime.utcnow()
            )
            
            if not include_completed:
                query = query.filter(FollowUp.status != FollowUpStatus.COMPLETED)
            
            if user_id:
                query = query.filter(Lead.assigned_user_id == user_id)
            
            # Order by priority and due date
            query = query.order_by(
                FollowUp.priority.desc(),
                FollowUp.due_date.asc()
            ).limit(limit)
            
            # Get the results
            results = query.all()
            
            # Format the results
            followups = []
            for followup, lead in results:
                followups.append({
                    "followup_id": followup.id,
                    "lead_id": lead.id,
                    "lead_name": lead.name,
                    "lead_email": lead.email,
                    "lead_phone": lead.phone,
                    "due_date": followup.due_date.isoformat(),
                    "status": followup.status.name,
                    "priority": followup.priority.name,
                    "notes": followup.notes,
                    "lead_score": lead.score
                })
            
            return followups
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def update_followup_status(
        cls,
        followup_id: int,
        status: FollowUpStatus,
        notes: Optional[str] = None,
        db: Session = None
    ) -> bool:
        """
        Update the status of a follow-up.
        
        Args:
            followup_id: The ID of the follow-up to update
            status: The new status of the follow-up
            notes: Optional notes to add to the follow-up
            db: Database session
            
        Returns:
            True if successful, False otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the follow-up
            followup = db.query(FollowUp).filter(
                FollowUp.id == followup_id
            ).first()
            
            if not followup:
                logger.error(f"Could not find follow-up with ID {followup_id}")
                return False
            
            # Update the follow-up
            followup.status = status
            
            if status == FollowUpStatus.COMPLETED:
                followup.completed_at = datetime.utcnow()
            
            if notes:
                # If there are existing notes, append the new notes
                if followup.notes:
                    followup.notes = f"{followup.notes}\n\n{datetime.utcnow().isoformat()}: {notes}"
                else:
                    followup.notes = f"{datetime.utcnow().isoformat()}: {notes}"
            
            db.commit()
            
            logger.info(f"Updated follow-up {followup_id} status to {status}")
            
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating follow-up status: {str(e)}")
            return False
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def reschedule_followup(
        cls,
        followup_id: int,
        new_due_date: datetime,
        priority: Optional[FollowUpPriority] = None,
        notes: Optional[str] = None,
        db: Session = None
    ) -> bool:
        """
        Reschedule a follow-up for a later date.
        
        Args:
            followup_id: The ID of the follow-up to reschedule
            new_due_date: The new due date for the follow-up
            priority: Optional new priority for the follow-up
            notes: Optional notes to add to the follow-up
            db: Database session
            
        Returns:
            True if successful, False otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the follow-up
            followup = db.query(FollowUp).filter(
                FollowUp.id == followup_id
            ).first()
            
            if not followup:
                logger.error(f"Could not find follow-up with ID {followup_id}")
                return False
            
            # Update the follow-up
            followup.due_date = new_due_date
            followup.status = FollowUpStatus.PENDING
            
            if priority:
                followup.priority = priority
            
            if notes:
                # If there are existing notes, append the new notes
                if followup.notes:
                    followup.notes = f"{followup.notes}\n\n{datetime.utcnow().isoformat()} (Rescheduled): {notes}"
                else:
                    followup.notes = f"{datetime.utcnow().isoformat()} (Rescheduled): {notes}"
            
            db.commit()
            
            logger.info(f"Rescheduled follow-up {followup_id} to {new_due_date}")
            
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Error rescheduling follow-up: {str(e)}")
            return False
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def create_followup_sequence(
        cls,
        lead_id: int,
        sequence_days: List[int],
        priority: FollowUpPriority = FollowUpPriority.MEDIUM,
        notes: Optional[str] = None,
        db: Session = None
    ) -> List[int]:
        """
        Create a sequence of follow-ups for a lead.
        
        Args:
            lead_id: The ID of the lead to create follow-ups for
            sequence_days: List of days from now to schedule follow-ups
            priority: The priority of the follow-ups
            notes: Optional notes to add to the follow-ups
            db: Database session
            
        Returns:
            List of IDs of the created follow-ups
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            followup_ids = []
            now = datetime.utcnow()
            
            for days in sequence_days:
                # Calculate the due date for this follow-up
                due_date = now + timedelta(days=days)
                
                # Create a note with the sequence information
                sequence_note = f"Part of follow-up sequence. Scheduled for day +{days}"
                if notes:
                    full_notes = f"{sequence_note}\n\n{notes}"
                else:
                    full_notes = sequence_note
                
                # Schedule the follow-up
                followup_id = cls.schedule_followup(
                    lead_id=lead_id,
                    due_date=due_date,
                    priority=priority,
                    notes=full_notes,
                    db=db
                )
                
                if followup_id:
                    followup_ids.append(followup_id)
            
            logger.info(f"Created follow-up sequence for lead {lead_id} with {len(followup_ids)} follow-ups")
            
            return followup_ids
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def analyze_followup_effectiveness(
        cls,
        user_id: Optional[int] = None,
        days: int = 30,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Analyze the effectiveness of follow-ups.
        
        Args:
            user_id: Optional ID of the user to analyze follow-ups for
            days: Number of days to analyze
            db: Database session
            
        Returns:
            Dictionary with effectiveness metrics
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            # Base query for follow-ups
            query = db.query(FollowUp).join(
                Lead, FollowUp.lead_id == Lead.id
            ).filter(
                FollowUp.created_at >= start_date
            )
            
            if user_id:
                query = query.filter(Lead.assigned_user_id == user_id)
            
            # Get all follow-ups in the time period
            all_followups = query.all()
            
            # Get completed follow-ups
            completed_followups = [f for f in all_followups if f.status == FollowUpStatus.COMPLETED]
            
            # Calculate metrics
            total_count = len(all_followups)
            completed_count = len(completed_followups)
            completion_rate = (completed_count / total_count) if total_count > 0 else 0
            
            # Calculate average completion time
            completion_times = []
            for f in completed_followups:
                if f.completed_at and f.created_at:
                    completion_time = (f.completed_at - f.created_at).total_seconds() / 3600  # in hours
                    completion_times.append(completion_time)
            
            avg_completion_time = sum(completion_times) / len(completion_times) if completion_times else 0
            
            # Calculate follow-ups by priority
            priority_counts = {
                "HIGH": len([f for f in all_followups if f.priority == FollowUpPriority.HIGH]),
                "MEDIUM": len([f for f in all_followups if f.priority == FollowUpPriority.MEDIUM]),
                "LOW": len([f for f in all_followups if f.priority == FollowUpPriority.LOW])
            }
            
            return {
                "total_followups": total_count,
                "completed_followups": completed_count,
                "completion_rate": completion_rate,
                "average_completion_time_hours": avg_completion_time,
                "followups_by_priority": priority_counts,
                "period_days": days
            }
        finally:
            if close_db:
                db.close() 