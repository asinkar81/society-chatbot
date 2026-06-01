"""
Router Agent - Intelligently routes user requests to appropriate agents using LLM
Uses Claude (via Anthropic or OpenRouter) to understand user intent and select the best agent(s)
"""
from typing import Dict, Any, List, Optional
import json
import re
import config


class RouterAgent:
    """Intelligent router that uses LLM to classify requests and route to appropriate agents"""

    AGENT_DESCRIPTIONS = {
        "invoice_agent": {
            "name": "Invoice Agent",
            "description": "Handles invoice generation, calculation, and management. Use for: creating invoices, generating bills, calculating amounts, etc.",
            "keywords": ["invoice", "bill", "demand", "generate invoices", "create invoices"],
        },
        "receipt_agent": {
            "name": "Receipt Agent",
            "description": "Processes payments and generates receipts. Use for: processing payments, handling payment screenshots, extracting payment details, generating receipts, etc.",
            "keywords": ["payment", "receipt", "screenshot", "paid", "process", "extract", "receipt"],
        },
        "ledger_agent": {
            "name": "Ledger Agent",
            "description": "Manages ledgers and financial records. Use for: viewing ledgers, checking balances, outstanding amounts, transaction history, etc.",
            "keywords": ["ledger", "account", "outstanding", "balance", "view", "transaction", "history"],
        },
        "admin_agent": {
            "name": "Admin Agent",
            "description": "Handles administrative tasks. Use for: updating rates, adding members, April 1st entries, system settings, member management, etc.",
            "keywords": ["rate", "setting", "member", "add", "april", "entry", "admin", "update", "config"],
        },
    }

    def __init__(self):
        """Initialize router with configured provider"""
        self.agent_descriptions = self.AGENT_DESCRIPTIONS
        self.provider = config.LLM_PROVIDER
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

    def route(self, user_input: str) -> Dict[str, Any]:
        """
        Intelligently route user input to appropriate agent(s)

        Returns:
            {
                "agent": "invoice_agent" | "receipt_agent" | "ledger_agent" | "admin_agent",
                "confidence": float (0-1),
                "intent": str,
                "reasoning": str,
                "clarification_needed": bool,
                "clarification_question": str (if needed)
            }
        """

        system_prompt = self._build_system_prompt()

        try:
            routing_result = self._llm_route(user_input, system_prompt)
            return routing_result
        except Exception as e:
            print(f"LLM routing failed: {e}, falling back to keyword matching")
            return self._fallback_route(user_input)

    def _build_system_prompt(self) -> str:
        """Build system prompt for LLM routing"""
        agents_info = "\n".join([
            f"- {info['name']}: {info['description']}"
            for info in self.agent_descriptions.values()
        ])

        return f"""You are an intelligent request router for a Society Management Chatbot.

Your job is to analyze user requests and determine which agent should handle them.

Available Agents:
{agents_info}

For each request, you must:
1. Understand the user's intent
2. Determine the best agent to handle it
3. Assess your confidence in the routing (0-1)
4. Identify if clarification is needed

IMPORTANT: You MUST respond with ONLY a valid JSON object, no other text.

Example JSON response:
{{
    "agent": "invoice_agent",
    "confidence": 0.95,
    "intent": "Generate invoices for fiscal year 2026-27",
    "reasoning": "User explicitly asked for invoice generation, which is the core responsibility of the Invoice Agent.",
    "clarification_needed": false,
    "clarification_question": null
}}

Example with clarification:
{{
    "agent": "receipt_agent",
    "confidence": 0.7,
    "intent": "Process a payment",
    "reasoning": "User mentioned payment processing, but details are vague. Could be ledger update or receipt generation.",
    "clarification_needed": true,
    "clarification_question": "Do you want to process a specific payment screenshot or update the ledger?"
}}

Rules:
- Always return valid JSON
- confidence should be between 0 and 1
- If uncertain between agents, set lower confidence and request clarification
- Be specific about the intent
- Provide clear reasoning
"""

    def _llm_route(self, user_input: str, system_prompt: str) -> Dict[str, Any]:
        """Use LLM to route the request"""
        try:
            if self.provider == "openrouter":
                response = self.client.chat.completions.create(
                    model=config.LLM_MODEL_MAIN,
                    max_tokens=config.LLM_MAX_TOKENS,
                    temperature=config.LLM_TEMPERATURE,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Route this request:\n\n{user_input}"},
                    ],
                )
                response_text = response.choices[0].message.content.strip()
            else:
                response = self.client.messages.create(
                    model=config.LLM_MODEL_MAIN,
                    max_tokens=config.LLM_MAX_TOKENS,
                    temperature=config.LLM_TEMPERATURE,
                    system=system_prompt,
                    messages=[
                        {
                            "role": "user",
                            "content": f"Route this request:\n\n{user_input}",
                        }
                    ],
                )
                response_text = response.content[0].text.strip()

            # Parse JSON response
            try:
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    routing_result = json.loads(json_match.group())
                else:
                    routing_result = json.loads(response_text)

                # Validate required fields
                required_fields = ["agent", "confidence", "intent", "reasoning", "clarification_needed"]
                if not all(field in routing_result for field in required_fields):
                    raise ValueError(f"Missing required fields in routing result")

                return routing_result
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Failed to parse LLM response: {response_text}")
                raise
        except Exception as e:
            print(f"LLM routing error: {e}")
            raise

    def _fallback_route(self, user_input: str) -> Dict[str, Any]:
        """Fallback keyword-based routing if LLM fails"""
        user_input_lower = user_input.lower()

        scores = {}
        for agent_id, agent_info in self.agent_descriptions.items():
            score = sum(
                1 for keyword in agent_info["keywords"]
                if keyword in user_input_lower
            )
            scores[agent_id] = score

        best_agent = max(scores, key=scores.get)
        confidence = min(scores[best_agent] / 3.0, 1.0)

        if confidence == 0:
            return {
                "agent": None,
                "confidence": 0,
                "intent": "Unknown",
                "reasoning": "Could not determine intent from keywords",
                "clarification_needed": True,
                "clarification_question": "What would you like to do? I can help with: invoices, payments/receipts, ledger/accounts, or admin tasks."
            }

        return {
            "agent": best_agent,
            "confidence": confidence,
            "intent": f"Matched to {self.agent_descriptions[best_agent]['name']}",
            "reasoning": "Keyword-based fallback routing",
            "clarification_needed": confidence < 0.7,
            "clarification_question": None if confidence >= 0.7 else "I'm not entirely sure. Did you mean...?"
        }

    @staticmethod
    def parse_agent_id(agent_name: str) -> Optional[str]:
        """Convert agent name to agent ID"""
        agent_map = {
            "invoice_agent": "invoice",
            "receipt_agent": "receipt",
            "ledger_agent": "ledger",
            "admin_agent": "admin",
        }
        return agent_map.get(agent_name)


_router = None


def get_router() -> RouterAgent:
    """Get or create router instance"""
    global _router
    if _router is None:
        _router = RouterAgent()
    return _router
