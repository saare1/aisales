import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from ..db.models import Notification, Lead

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Service for managing notifications and alerts.
    """
    
    @classmethod
    def create_notification(
        cls,
        lead_id: int,
        notification_type: str,
        content: str,
        db: Session,
        priority: int = 1
    ) -> Notification:
        """
        Create a new notification for a lead.
        
        Args:
            lead_id: ID of the lead
            notification_type: Type of notification
            content: Content of the notification
            db: Database session
            priority: Priority level (1=low, 2=medium, 3=high)
            
        Returns:
            The created Notification object
        """
        try:
            # Check if lead exists
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                logger.error(f"Lead with ID {lead_id} not found")
                raise ValueError(f"Lead with ID {lead_id} not found")
            
            # Create notification
            notification = Notification(
                lead_id=lead_id,
                notification_type=notification_type,
                content=content,
                is_read=False,
                is_handled=False,
                created_at=datetime.utcnow()
            )
            
            db.add(notification)
            db.commit()
            db.refresh(notification)
            
            logger.info(f"Created {notification_type} notification for lead {lead.email}")
            
            return notification
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating notification: {str(e)}")
            raise
    
    @classmethod
    def mark_as_read(cls, notification_id: int, db: Session) -> bool:
        """
        Mark a notification as read.
        
        Args:
            notification_id: ID of the notification
            db: Database session
            
        Returns:
            Boolean indicating success
        """
        try:
            notification = db.query(Notification).filter(Notification.id == notification_id).first()
            if not notification:
                logger.error(f"Notification with ID {notification_id} not found")
                return False
            
            notification.is_read = True
            notification.read_at = datetime.utcnow()
            
            db.commit()
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error marking notification as read: {str(e)}")
            return False
    
    @classmethod
    def mark_as_handled(cls, notification_id: int, db: Session) -> bool:
        """
        Mark a notification as handled.
        
        Args:
            notification_id: ID of the notification
            db: Database session
            
        Returns:
            Boolean indicating success
        """
        try:
            notification = db.query(Notification).filter(Notification.id == notification_id).first()
            if not notification:
                logger.error(f"Notification with ID {notification_id} not found")
                return False
            
            notification.is_handled = True
            
            db.commit()
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error marking notification as handled: {str(e)}")
            return False
    
    @classmethod
    def get_unread_notifications(cls, db: Session, limit: int = 50) -> List[Notification]:
        """
        Get all unread notifications.
        
        Args:
            db: Database session
            limit: Maximum number of notifications to return
            
        Returns:
            List of unread Notification objects
        """
        try:
            notifications = db.query(Notification).filter(
                Notification.is_read == False
            ).order_by(
                Notification.created_at.desc()
            ).limit(limit).all()
            
            return notifications
            
        except Exception as e:
            logger.error(f"Error getting unread notifications: {str(e)}")
            return []
    
    @classmethod
    def get_unhandled_notifications(cls, db: Session, limit: int = 50) -> List[Notification]:
        """
        Get all unhandled notifications.
        
        Args:
            db: Database session
            limit: Maximum number of notifications to return
            
        Returns:
            List of unhandled Notification objects
        """
        try:
            notifications = db.query(Notification).filter(
                Notification.is_handled == False
            ).order_by(
                Notification.created_at.desc()
            ).limit(limit).all()
            
            return notifications
            
        except Exception as e:
            logger.error(f"Error getting unhandled notifications: {str(e)}")
            return []
    
    @classmethod
    def get_notifications_for_lead(cls, lead_id: int, db: Session, limit: int = 20) -> List[Notification]:
        """
        Get notifications for a specific lead.
        
        Args:
            lead_id: ID of the lead
            db: Database session
            limit: Maximum number of notifications to return
            
        Returns:
            List of Notification objects for the lead
        """
        try:
            notifications = db.query(Notification).filter(
                Notification.lead_id == lead_id
            ).order_by(
                Notification.created_at.desc()
            ).limit(limit).all()
            
            return notifications
            
        except Exception as e:
            logger.error(f"Error getting notifications for lead {lead_id}: {str(e)}")
            return [] 