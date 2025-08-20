import re
import json

def clean_llm_json(response):
    """
    Remove markdown code blocks and parse JSON from LLM response.
    
    Args:
        response (str or response object): Raw LLM response
        
    Returns:
        dict/list: Parsed JSON data, or None if parsing fails
    """
    if not response:
        return None
    
    # Handle different response types
    if hasattr(response, 'text'):
        # For Google Gemini GenerateContentResponse
        text = response.text
    elif hasattr(response, 'content'):
        # For other response objects
        text = response.content
    elif isinstance(response, str):
        # Already a string
        text = response
    else:
        # Try to convert to string
        text = str(response)
    
    # Remove markdown code blocks (handles both ```json and plain ```)
    cleaned = re.sub(r'```(?:json|javascript)?\s*\n?(.*?)\n?```', r'\1', text, flags=re.DOTALL)
    
    # Clean up whitespace
    cleaned = cleaned.strip()
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # If that fails, try to find JSON structure directly
        json_match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        return None