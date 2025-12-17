"""
LLM Configuration for Business Name Standardization

This module configures the local Ollama LLM specifically for business name extraction
and standardization. The model can be fine-tuned with custom training data for improved accuracy.

Usage:
    from config.llm_config import StandardizationLLM

    llm = StandardizationLLM()
    result = llm.extract_business_name(title, domain, original_name)
"""

import os
import re
import httpx
from pathlib import Path
from typing import Optional, Dict, Any

# Base paths
CONFIG_DIR = Path(__file__).parent
PROMPTS_DIR = CONFIG_DIR.parent / "prompts"
MODELS_DIR = CONFIG_DIR.parent / "models"


class StandardizationLLM:
    """
    Dedicated LLM for business name standardization and extraction.

    Default model: llama3.2:3b (can be swapped for fine-tuned version)

    To use a fine-tuned model:
        1. Train with: ollama create standardization-llm -f models/Modelfile
        2. Set: llm = StandardizationLLM(model="standardization-llm")
    """

    # Model configuration
    DEFAULT_MODEL = "llama3.2:3b"
    FINETUNED_MODEL = "standardization-llm"  # Name for fine-tuned model

    # Ollama settings
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

    # Generation parameters optimized for extraction tasks
    DEFAULT_OPTIONS = {
        "temperature": 0.1,      # Low temp for consistent outputs
        "num_predict": 50,       # Short responses (just the name)
        "top_p": 0.9,
        "repeat_penalty": 1.1,
    }

    def __init__(self, model: str = None, use_finetuned: bool = False):
        """
        Initialize the verification LLM.

        Args:
            model: Specific model name to use (overrides defaults)
            use_finetuned: If True, use the fine-tuned model if available
        """
        if model:
            self.model = model
        elif use_finetuned:
            self.model = self.FINETUNED_MODEL
        else:
            self.model = self.DEFAULT_MODEL

        self.api_url = f"{self.OLLAMA_URL}/api/generate"
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load the business name extraction prompt template."""
        prompt_file = PROMPTS_DIR / "business_name_extraction.txt"
        if prompt_file.exists():
            return prompt_file.read_text()
        else:
            # Fallback to embedded prompt
            return self._get_default_prompt()

    def _get_default_prompt(self) -> str:
        """Default prompt if file not found."""
        return '''You are extracting business names from website titles for a pressure washing/cleaning company database.

TASK: Extract the COMPLETE business name from this title.

INPUT:
- Title: "{title}"
- Domain: {domain}
- Current DB name: "{original_name}"

UNDERSTANDING BUSINESS NAMES:

1. Many businesses have service words IN their name - this is VALID:
   - "River City Pressure Washing" - full business name (includes location + service)
   - "Austin Power Wash" - full business name (includes city + service)
   - "Lone Star Soft Wash" - full business name (includes branded term + service)
   - "Mike's Pressure Washing" - full business name (person's name + service)
   - "Elite Exterior Cleaning" - full business name (adjective + service)

2. What is NOT a business name (just generic descriptions):
   - "Pressure Washing Services" - no unique identifier
   - "Soft Washing Dallas" - just service + city, no business identity
   - "Professional Cleaning" - too generic
   - "Home", "Contact Us", "About" - navigation pages

3. The KEY difference:
   - BUSINESS NAME = has a unique/branded element (person name, location name, creative word)
   - NOT A NAME = just describes the service with no unique identifier

TITLE PATTERNS:
- "Service in City | BUSINESS NAME" → extract the business name after |
- "BUSINESS NAME | Service Description" → extract before |
- "Home | BUSINESS NAME" → ignore "Home", take what's after |
- "Welcome to BUSINESS NAME" → remove "Welcome to"

EXAMPLES (study carefully - notice how service words ARE part of names):
Title: "Pressure Washing San Antonio | River City Pressure Washing" → River City Pressure Washing
Title: "Home | Mike's Power Washing" → Mike's Power Washing
Title: "Austin Soft Wash | Residential & Commercial" → Austin Soft Wash
Title: "Lone Star Exterior Cleaning - Home" → Lone Star Exterior Cleaning
Title: "Welcome to Elite Pressure Pros" → Elite Pressure Pros
Title: "Squeaky Clean Window Washing | Dallas Fort Worth" → Squeaky Clean Window Washing
Title: "Pressure Washing Omaha | Hydro Softwash" → Hydro Softwash
Title: "BlueWave Softwash | Soft Washing & Pressure Washing" → BlueWave Softwash
Title: "Pressure Washing Services" → NONE (no unique identifier)
Title: "Professional Cleaning Dallas" → NONE (too generic)
Title: "Contact Us | ABC Company" → ABC Company

NOW EXTRACT FROM: "{title}"
- Include the FULL business name even if it contains service words
- Look for unique identifiers (names, locations, creative words)
- Remove LLC/Inc/Co suffixes
- If truly no business name exists, return: NONE

ANSWER (just the name):'''

    def extract_business_name(
        self,
        title: str,
        domain: str,
        original_name: str = "Unknown",
        timeout: float = 30.0
    ) -> Optional[str]:
        """
        Extract business name from website title.

        Args:
            title: Website <title> tag content
            domain: Website domain (e.g., "example.com")
            original_name: Current name in database
            timeout: Request timeout in seconds

        Returns:
            Extracted business name or None if extraction failed
        """
        # Build prompt
        prompt = self.prompt_template.format(
            title=title,
            domain=domain,
            original_name=original_name
        )

        try:
            response = httpx.post(
                self.api_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": self.DEFAULT_OPTIONS
                },
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                name = result.get("response", "").strip()
                return self._clean_response(name)

        except Exception as e:
            print(f"LLM extraction error: {e}")

        return None

    def _clean_response(self, name: str) -> Optional[str]:
        """Clean and validate LLM response."""
        if not name:
            return None

        # Remove quotes
        name = name.strip('"\'')

        # Remove common prefixes from LLM responses
        name = re.sub(
            r'^(Business name:|Name:|The business name is:?|ANSWER:?)\s*',
            '',
            name,
            flags=re.IGNORECASE
        )
        name = name.strip()

        # Validate
        if name.upper() == "NONE" or len(name) < 3 or len(name) > 60:
            return None
        if name.lower() in ['none', 'n/a', 'unknown', 'not found', 'null']:
            return None

        return name

    def check_model_available(self) -> bool:
        """Check if the configured model is available in Ollama."""
        try:
            response = httpx.get(f"{self.OLLAMA_URL}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "").split(":")[0] for m in models]
                return self.model.split(":")[0] in model_names
        except:
            pass
        return False

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model."""
        return {
            "model": self.model,
            "api_url": self.api_url,
            "available": self.check_model_available(),
            "options": self.DEFAULT_OPTIONS,
            "prompt_source": "file" if (PROMPTS_DIR / "business_name_extraction.txt").exists() else "embedded"
        }


# Convenience function for quick access
def get_standardization_llm(use_finetuned: bool = False) -> StandardizationLLM:
    """Get a configured StandardizationLLM instance."""
    return StandardizationLLM(use_finetuned=use_finetuned)


# Test function
def test_llm():
    """Test the standardization LLM with sample data."""
    llm = StandardizationLLM()

    print(f"Model: {llm.model}")
    print(f"Available: {llm.check_model_available()}")
    print()

    test_cases = [
        ("Home | River City Pressure Washing", "rivercitypw.com"),
        ("Pressure Washing Omaha | Hydro Softwash", "hydrosoftwash.com"),
        ("Pressure Washing Services", "generic.com"),
    ]

    for title, domain in test_cases:
        result = llm.extract_business_name(title, domain)
        print(f"Title: {title}")
        print(f"  → {result}")
        print()


if __name__ == "__main__":
    test_llm()
