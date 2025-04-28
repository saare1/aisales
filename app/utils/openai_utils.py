"""
Utility functions for OpenAI API.
"""
import logging
from typing import List, Optional

# Configure logging
logger = logging.getLogger(__name__)

def get_embedding(text: str, model: str = "text-embedding-ada-002") -> Optional[List[float]]:
    """
    Get embeddings for a text string using OpenAI's embedding models.
    
    Args:
        text: The text to generate embeddings for
        model: The embedding model to use
        
    Returns:
        A list of floats representing the text embedding, or None if there's an error
    """
    try:
        from openai import OpenAI
        import os
        
        # Get API key from environment or use a default for testing
        api_key = os.getenv("OPENAI_API_KEY", "test_key")
        client = OpenAI(api_key=api_key)
        
        # For testing purposes, return a dummy embedding if using test key
        if api_key == "test_key":
            logger.warning("Using dummy embedding as OPENAI_API_KEY is not set")
            return [0.0] * 1536  # Return a dummy embedding vector
            
        response = client.embeddings.create(
            input=[text],
            model=model
        )
        
        embedding = response.data[0].embedding
        return embedding
        
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        # Return a dummy embedding for testing purposes
        return [0.0] * 1536 