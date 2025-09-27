import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

def get_gemini_client():
    """Initialize and return a Gemini client."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables")
    
    client = genai.Client(api_key=api_key)
    return client