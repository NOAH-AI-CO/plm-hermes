import os
import logging
import json
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

def rewrite_query(query: str, question_type: str = "General", occasion: str = "General") -> str:
    """
    Rewrite and expand the user query using Google GenAI.
    """
    # Environment setup for Google GenAI
    # Using path from user configuration
    gcp_key_path = "/Users/andy/repos/NoahAgent/noah_agent/gcp_key.json"
    
    # Ensure credentials are set
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        if os.path.exists(gcp_key_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path
        else:
             # Fallback: try to find it relative to project root if absolute path fails
             base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
             alt_path = os.path.join(base_dir, "gcp_key.json")
             if os.path.exists(alt_path):
                  os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = alt_path

    # Set required environment variables for the client
    os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
    os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
    os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

    try:
        client = genai.Client(http_options=types.HttpOptions(api_version="v1"))
        
        prompt = f"""You are an expert prompt engineer. Rewrite and expand the following user query to be more comprehensive and effective.

User Query: {query}

Rewrite the query to be clearer, more detailed, and optimized for achieving the best results. Output ONLY the rewritten query text."""

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={"type": "STRING"},
                temperature=0.3,
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            ),
        )
        
        if not response.text:
            return ""
            
        return json.loads(response.text)
        
    except Exception as e:
        logger.error(f"Error in rewrite_query: {e}")
        raise e
