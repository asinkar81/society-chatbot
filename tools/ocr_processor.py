"""
OCR and vision processing for payment screenshots
Supports both Anthropic direct API and OpenRouter
"""
from pathlib import Path
from typing import Dict, Any, Optional
import base64
import json
import config


class OCRProcessor:
    """Process payment screenshots using Claude vision"""

    def __init__(self):
        """Initialize OCR processor with configured API provider"""
        self.provider = config.LLM_PROVIDER
        self.model = config.LLM_MODEL_VISION
        self.client = self._create_client()

    def _create_client(self):
        """Create LLM client based on configured provider"""
        if config.LLM_PROVIDER == "openrouter":
            if not config.OPENROUTER_API_KEY:
                raise ValueError("OPENROUTER_API_KEY environment variable not set")

            from openai import OpenAI

            return OpenAI(
                api_key=config.OPENROUTER_API_KEY,
                base_url=config.OPENROUTER_BASE_URL,
                default_headers={
                    "HTTP-Referer": config.OPENROUTER_SITE_URL,
                    "X-Title": config.OPENROUTER_SITE_NAME,
                },
            )
        else:
            if not config.ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")

            from anthropic import Anthropic
            return Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def extract_payment_details(self, image_path: Path) -> Optional[Dict[str, Any]]:
        """
        Extract payment details from screenshot using Claude vision
        Works with both Anthropic API and OpenRouter
        Returns: {amount, date, transaction_id, payment_method}
        """
        try:
            with open(image_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

            suffix = image_path.suffix.lower()
            media_type_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            media_type = media_type_map.get(suffix, "image/jpeg")

            if self.provider == "openrouter":
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{media_type};base64,{image_data}"
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": """Extract payment details from this screenshot. 
Return JSON with these fields (if visible):
- amount: numeric amount paid
- currency: currency type (INR, USD, etc)
- date: payment date (DD-MM-YYYY format)
- transaction_id: transaction ID or reference number
- payment_method: method (UPI, Bank Transfer, Cash, etc)
- description: any payment description or note

Return ONLY valid JSON, no markdown formatting.
If a field is not visible, use null for that field.""",
                                },
                            ],
                        }
                    ],
                )
                response_text = response.choices[0].message.content.strip()
            else:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": image_data,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": """Extract payment details from this screenshot. 
Return JSON with these fields (if visible):
- amount: numeric amount paid
- currency: currency type (INR, USD, etc)
- date: payment date (DD-MM-YYYY format)
- transaction_id: transaction ID or reference number
- payment_method: method (UPI, Bank Transfer, Cash, etc)
- description: any payment description or note

Return ONLY valid JSON, no markdown formatting.
If a field is not visible, use null for that field.""",
                                },
                            ],
                        }
                    ],
                )
                response_text = message.content[0].text.strip()

            try:
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]

                payment_details = json.loads(response_text.strip())
                return payment_details
            except json.JSONDecodeError:
                return {
                    "error": "Could not parse payment details",
                    "raw_response": response_text,
                }

        except Exception as e:
            return {"error": str(e)}

    def validate_payment_details(self, details: Dict[str, Any]) -> bool:
        """Validate extracted payment details"""
        required_fields = ["amount"]
        return all(details.get(field) is not None for field in required_fields)
