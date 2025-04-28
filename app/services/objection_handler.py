import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models import Lead, Conversation, ObjectionLibrary, DetectedObjection, ObjectionType

# Configure logging
logger = logging.getLogger(__name__)


class ObjectionHandler:
    """
    Service for detecting, logging, and handling sales objections.
    
    This service provides:
    1. Detection of objections in lead messages
    2. Retrieval of appropriate responses based on objection type
    3. Tracking of objections and resolution success rates
    """
    
    @classmethod
    def detect_objection(
        cls, 
        message_content: str, 
        lead_id: int, 
        db: Session = None
    ) -> Optional[Tuple[ObjectionType, str, str]]:
        """
        Detect if a message contains an objection.
        
        Args:
            message_content: The content of the message to analyze
            lead_id: The ID of the lead who sent the message
            db: Database session
            
        Returns:
            Tuple of (objection_type, objection_text, suggested_response) if objection found,
            None otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Convert message to lowercase for easier matching
            message_lower = message_content.lower()
            
            # Get all objection patterns from the library
            objection_library = db.query(ObjectionLibrary).all()
            
            for objection_entry in objection_library:
                # Check if any keywords match
                for keyword in objection_entry.keywords.split(','):
                    keyword = keyword.strip().lower()
                    if keyword and keyword in message_lower:
                        # Match found, return objection type and response
                        cls._log_detected_objection(
                            lead_id, 
                            message_content, 
                            objection_entry.objection_type,
                            objection_entry.id,
                            db
                        )
                        
                        return (
                            objection_entry.objection_type, 
                            objection_entry.objection_text, 
                            objection_entry.suggested_response
                        )
                        
            # No match found
            return None
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def _log_detected_objection(
        cls,
        lead_id: int,
        message_content: str,
        objection_type: ObjectionType,
        objection_library_id: int,
        db: Session
    ) -> None:
        """
        Log a detected objection in the database.
        
        Args:
            lead_id: The ID of the lead who raised the objection
            message_content: The content of the message with the objection
            objection_type: The type of objection detected
            objection_library_id: The ID of the matching library entry
            db: Database session
        """
        try:
            # Create a new detected objection record
            detected_objection = DetectedObjection(
                lead_id=lead_id,
                objection_library_id=objection_library_id,
                objection_type=objection_type,
                message_text=message_content,
                detected_at=datetime.utcnow(),
                is_resolved=False
            )
            
            db.add(detected_objection)
            db.commit()
            
            logger.info(f"Detected objection from lead {lead_id}: {objection_type}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error logging detected objection: {str(e)}")
    
    @classmethod
    def mark_objection_resolved(
        cls,
        objection_id: int,
        is_resolved: bool = True,
        db: Session = None
    ) -> bool:
        """
        Mark an objection as resolved or unresolved.
        
        Args:
            objection_id: The ID of the detected objection
            is_resolved: Whether the objection is resolved
            db: Database session
            
        Returns:
            True if successful, False otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get the objection
            objection = db.query(DetectedObjection).filter(
                DetectedObjection.id == objection_id
            ).first()
            
            if not objection:
                logger.error(f"Could not find objection with ID {objection_id}")
                return False
            
            # Update the objection
            objection.is_resolved = is_resolved
            objection.resolved_at = datetime.utcnow() if is_resolved else None
            
            db.commit()
            
            logger.info(f"Marked objection {objection_id} as {'resolved' if is_resolved else 'unresolved'}")
            
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Error marking objection as resolved: {str(e)}")
            return False
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def get_suggested_response(
        cls,
        objection_type: ObjectionType,
        business_id: Optional[int] = None,
        db: Session = None
    ) -> Optional[str]:
        """
        Get a suggested response for a specific objection type.
        Optionally filtered by business ID for custom responses.
        
        Args:
            objection_type: The type of objection
            business_id: Optional business ID for custom responses
            db: Database session
            
        Returns:
            Suggested response text if found, None otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            query = db.query(ObjectionLibrary).filter(
                ObjectionLibrary.objection_type == objection_type
            )
            
            if business_id:
                # First try to find a business-specific response
                business_response = query.filter(
                    ObjectionLibrary.business_id == business_id
                ).first()
                
                if business_response:
                    return business_response.suggested_response
            
            # Fall back to default response (business_id is null)
            default_response = query.filter(
                ObjectionLibrary.business_id.is_(None)
            ).first()
            
            if default_response:
                return default_response.suggested_response
            
            return None
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def get_common_objections_for_lead(
        cls,
        lead_id: int,
        limit: int = 5,
        db: Session = None
    ) -> List[Dict]:
        """
        Get the most common objections raised by a lead.
        
        Args:
            lead_id: The ID of the lead
            limit: The maximum number of objections to return
            db: Database session
            
        Returns:
            List of dictionaries with objection information
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Get all objections for this lead
            objections = db.query(DetectedObjection).filter(
                DetectedObjection.lead_id == lead_id
            ).order_by(DetectedObjection.detected_at.desc()).limit(limit).all()
            
            result = []
            for obj in objections:
                # Get the library entry
                library_entry = db.query(ObjectionLibrary).filter(
                    ObjectionLibrary.id == obj.objection_library_id
                ).first()
                
                if library_entry:
                    result.append({
                        "objection_id": obj.id,
                        "objection_type": obj.objection_type.name,
                        "message_text": obj.message_text,
                        "detected_at": obj.detected_at.isoformat(),
                        "is_resolved": obj.is_resolved,
                        "resolved_at": obj.resolved_at.isoformat() if obj.resolved_at else None,
                        "suggested_response": library_entry.suggested_response
                    })
            
            return result
        finally:
            if close_db:
                db.close()
    
    @classmethod
    def create_objection_template(
        cls,
        objection_type: ObjectionType,
        keywords: str,
        objection_text: str,
        suggested_response: str,
        business_id: Optional[int] = None,
        db: Session = None
    ) -> Optional[int]:
        """
        Create a new objection template in the library.
        
        Args:
            objection_type: The type of objection
            keywords: Comma-separated list of keywords to detect this objection
            objection_text: Example text of the objection
            suggested_response: Suggested response to the objection
            business_id: Optional business ID for business-specific templates
            db: Database session
            
        Returns:
            ID of the created objection template if successful, None otherwise
        """
        close_db = False
        if db is None:
            db = get_db_session()
            close_db = True
        
        try:
            # Create a new objection template
            objection_template = ObjectionLibrary(
                objection_type=objection_type,
                keywords=keywords,
                objection_text=objection_text,
                suggested_response=suggested_response,
                business_id=business_id,
                created_at=datetime.utcnow()
            )
            
            db.add(objection_template)
            db.commit()
            
            logger.info(f"Created new objection template: {objection_type}")
            
            return objection_template.id
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating objection template: {str(e)}")
            return None
        finally:
            if close_db:
                db.close() 