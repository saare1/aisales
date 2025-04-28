import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session
from openai import OpenAI

from ..db.models import Lead, Conversation, Product, ProductRecommendation, UserPreference
from ..utils.openai_utils import get_embedding

logger = logging.getLogger(__name__)

class ProductRecommendationEngine:
    """
    Service for analyzing lead conversations and suggesting personalized product recommendations.
    """
    
    def __init__(self, db: Session, openai_api_key: str):
        """
        Initialize the ProductRecommendationEngine.
        
        Args:
            db: Database session
            openai_api_key: OpenAI API key for analyzing conversations
        """
        self.db = db
        self.client = OpenAI(api_key=openai_api_key)
        
    def extract_preferences_from_conversation(self, lead_id: int) -> List[Dict[str, Any]]:
        """
        Analyze conversations with a lead to extract their preferences and interests.
        
        Args:
            lead_id: The ID of the lead
            
        Returns:
            A list of extracted preferences
        """
        lead = self.db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            logger.error(f"Lead with ID {lead_id} not found")
            return []
            
        # Get all messages from the conversation
        conversations = self.db.query(Conversation).filter(
            Conversation.lead_id == lead_id
        ).order_by(Conversation.timestamp.asc()).all()
        
        if not conversations:
            logger.info(f"No conversations found for lead {lead_id}")
            return []
        
        # Combine all messages into a single context
        conversation_text = "\n".join([
            f"{'Lead' if conv.is_from_lead else 'Agent'}: {conv.message}"
            for conv in conversations
        ])
        
        # Use OpenAI to extract preferences
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an AI designed to extract customer preferences from sales conversations. Identify key interests, needs, pain points, budget constraints, and feature preferences."},
                    {"role": "user", "content": f"Extract customer preferences from this conversation:\n\n{conversation_text}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            # Parse the response
            preferences_data = response.choices[0].message.content
            
            # Store preferences in the database
            self._save_preferences(lead_id, preferences_data)
            
            return preferences_data
            
        except Exception as e:
            logger.error(f"Error extracting preferences: {str(e)}")
            return []
    
    def _save_preferences(self, lead_id: int, preferences_data: Dict[str, Any]) -> None:
        """
        Save extracted preferences to the database.
        
        Args:
            lead_id: The ID of the lead
            preferences_data: Dictionary of preferences extracted from conversation
        """
        try:
            # Clear existing preferences for this lead
            self.db.query(UserPreference).filter(UserPreference.lead_id == lead_id).delete()
            
            # Add new preferences
            for pref_type, values in preferences_data.items():
                if isinstance(values, list):
                    for value in values:
                        strength = 0.8  # Default strength
                        if isinstance(value, dict) and "value" in value and "strength" in value:
                            pref_value = value["value"]
                            strength = value["strength"]
                        else:
                            pref_value = value
                            
                        preference = UserPreference(
                            lead_id=lead_id,
                            preference_type=pref_type,
                            preference_value=str(pref_value),
                            preference_strength=strength
                        )
                        self.db.add(preference)
                else:
                    preference = UserPreference(
                        lead_id=lead_id,
                        preference_type=pref_type,
                        preference_value=str(values),
                        preference_strength=0.8
                    )
                    self.db.add(preference)
                    
            self.db.commit()
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error saving preferences: {str(e)}")
    
    def generate_recommendations(self, lead_id: int, max_recommendations: int = 3) -> List[Dict[str, Any]]:
        """
        Generate product recommendations for a lead based on their preferences and conversation history.
        
        Args:
            lead_id: The ID of the lead
            max_recommendations: Maximum number of recommendations to generate
            
        Returns:
            A list of recommended products with confidence scores and reasons
        """
        # First ensure we have up-to-date preferences
        self.extract_preferences_from_conversation(lead_id)
        
        # Get lead and their preferences
        lead = self.db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            logger.error(f"Lead with ID {lead_id} not found")
            return []
        
        preferences = self.db.query(UserPreference).filter(
            UserPreference.lead_id == lead_id
        ).all()
        
        # Get all available products
        products = self.db.query(Product).filter(Product.is_active == True).all()
        if not products:
            logger.info("No active products found in the catalog")
            return []
        
        # Get the most recent conversation messages for context
        recent_messages = self.db.query(Conversation).filter(
            Conversation.lead_id == lead_id
        ).order_by(Conversation.timestamp.desc()).limit(10).all()
        
        recent_messages.reverse()  # Chronological order
        conversation_context = "\n".join([
            f"{'Lead' if msg.is_from_lead else 'Agent'}: {msg.message}"
            for msg in recent_messages
        ])
        
        # Construct the products info
        products_info = []
        for product in products:
            features = [f.name for f in product.features]
            product_info = {
                "id": product.id,
                "name": product.name,
                "price": product.base_price,
                "description": product.description,
                "category": product.category.name if product.category else "Uncategorized",
                "features": features,
                "benefits": product.benefits if product.benefits else [],
                "target_audience": product.target_audience if product.target_audience else []
            }
            products_info.append(product_info)
            
        # Create preference context
        preferences_context = [
            f"{pref.preference_type}: {pref.preference_value} (strength: {pref.preference_strength})"
            for pref in preferences
        ]
        
        # Use AI to match preferences to products
        try:
            prompt = f"""
            LEAD INFORMATION:
            Email: {lead.email}
            Status: {lead.status}
            Company: {lead.company_name if lead.company_name else 'Not specified'}
            Industry: {lead.industry if lead.industry else 'Not specified'}
            Role: {lead.job_title if lead.job_title else 'Not specified'}
            
            PREFERENCES DETECTED:
            {'\n'.join(preferences_context) if preferences_context else 'No specific preferences detected yet.'}
            
            RECENT CONVERSATION:
            {conversation_context}
            
            AVAILABLE PRODUCTS:
            {products_info}
            
            Based on the lead's information, detected preferences, and conversation history, recommend up to {max_recommendations} products that would best fit their needs.
            For each recommendation, provide:
            1. Product ID
            2. Confidence score (0.0-1.0)
            3. List of specific reasons why this product matches their needs
            4. Suggestions for how to position this product when presenting it to the lead
            """
            
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an AI sales assistant that specializes in matching customer needs with relevant products."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            recommendations_data = response.choices[0].message.content
            
            # Save recommendations to database
            self._save_recommendations(lead_id, recommendations_data)
            
            return recommendations_data
            
        except Exception as e:
            logger.error(f"Error generating recommendations: {str(e)}")
            return []
    
    def _save_recommendations(self, lead_id: int, recommendations_data: Dict[str, Any]) -> None:
        """
        Save generated recommendations to the database.
        
        Args:
            lead_id: The ID of the lead
            recommendations_data: Dictionary of recommended products with reasoning
        """
        try:
            # Parse the recommendations
            recommendations = recommendations_data.get("recommendations", [])
            
            for rec in recommendations:
                product_id = rec.get("product_id")
                confidence = rec.get("confidence_score", 0.5)
                reasons = rec.get("reasons", [])
                
                # Check if product exists
                product = self.db.query(Product).filter(Product.id == product_id).first()
                if not product:
                    logger.warning(f"Product with ID {product_id} not found, skipping recommendation")
                    continue
                
                # Create or update recommendation
                existing_rec = self.db.query(ProductRecommendation).filter(
                    ProductRecommendation.lead_id == lead_id,
                    ProductRecommendation.product_id == product_id
                ).first()
                
                if existing_rec:
                    existing_rec.confidence_score = confidence
                    existing_rec.reasons = reasons
                    existing_rec.recommended_at = datetime.utcnow()
                else:
                    new_rec = ProductRecommendation(
                        lead_id=lead_id,
                        product_id=product_id,
                        confidence_score=confidence,
                        reasons=reasons,
                        recommended_at=datetime.utcnow()
                    )
                    self.db.add(new_rec)
            
            self.db.commit()
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error saving recommendations: {str(e)}")
    
    def get_lead_recommendations(self, lead_id: int) -> List[Dict[str, Any]]:
        """
        Get existing recommendations for a lead.
        
        Args:
            lead_id: The ID of the lead
            
        Returns:
            A list of product recommendations for the lead
        """
        try:
            recommendations = self.db.query(ProductRecommendation).filter(
                ProductRecommendation.lead_id == lead_id
            ).order_by(
                ProductRecommendation.confidence_score.desc()
            ).all()
            
            result = []
            for rec in recommendations:
                product = self.db.query(Product).filter(Product.id == rec.product_id).first()
                if product:
                    result.append({
                        "recommendation_id": rec.id,
                        "product_id": product.id,
                        "product_name": product.name,
                        "product_description": product.description,
                        "price": product.base_price,
                        "confidence_score": rec.confidence_score,
                        "reasons": rec.reasons,
                        "recommended_at": rec.recommended_at.isoformat(),
                        "was_accepted": rec.was_accepted
                    })
            
            return result
            
        except Exception as e:
            logger.error(f"Error retrieving recommendations: {str(e)}")
            return []
    
    def mark_recommendation_accepted(self, recommendation_id: int, accepted: bool = True) -> bool:
        """
        Mark a recommendation as accepted or rejected by the lead.
        
        Args:
            recommendation_id: The ID of the recommendation
            accepted: Whether the recommendation was accepted
            
        Returns:
            Boolean indicating success
        """
        try:
            recommendation = self.db.query(ProductRecommendation).filter(
                ProductRecommendation.id == recommendation_id
            ).first()
            
            if not recommendation:
                logger.error(f"Recommendation with ID {recommendation_id} not found")
                return False
            
            recommendation.was_accepted = accepted
            self.db.commit()
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating recommendation: {str(e)}")
            return False 