"""
Base agent class using LangChain with support for Anthropic and OpenRouter APIs
"""
import json
import re
import inspect
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable, Union
from langchain.agents import AgentExecutor, ZeroShotAgent, Tool
from langchain import LLMChain
import config
from data_providers.base_provider import DataProvider
from file_storage.base_storage import FileStorage


def _parse_and_call(func, input_str: str) -> str:
    """Parse a single string input and call func with the right arguments.
    
    LangChain Tool passes Action Input as a single string. Multi-param
    functions need their args parsed from that string.
    """
    input_str = input_str.strip()
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    required = [p for p in params if p.default == inspect.Parameter.empty
                and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                               inspect.Parameter.POSITIONAL_OR_KEYWORD)]

    if not input_str:
        return func()

    # Strategy 1: JSON dict
    if input_str.startswith("{"):
        try:
            kwargs = json.loads(input_str)
            if isinstance(kwargs, dict):
                return func(**kwargs)
        except (json.JSONDecodeError, TypeError):
            pass

    # Strategy 2: key=value pairs
    kv = re.findall(r'(\w+)\s*=\s*([^,]+)', input_str)
    if kv:
        kwargs = {}
        for k, v in kv:
            kwargs[k] = v.strip().strip('"\'')
        try:
            return func(**kwargs)
        except Exception:
            pass

    # Strategy 3: comma-separated with type coercion
    parts = [p.strip().strip('"\'') for p in input_str.split(",")]
    converted = []
    for i, part in enumerate(parts):
        if i < len(params):
            ann = params[i].annotation
            if ann != inspect.Parameter.empty and ann != str:
                try:
                    converted.append(ann(part))
                except (ValueError, TypeError):
                    converted.append(part)
            else:
                converted.append(part)
        else:
            converted.append(part)
    try:
        return func(*converted)
    except Exception:
        pass

    # Fallback: pass whole string as first positional arg
    return func(input_str)


def create_llm(model: str, use_vision: bool = False):
    """
    Create LLM instance based on configured provider.
    For OpenRouter: uses ChatOpenAI (OpenAI-compatible endpoint /v1/chat/completions),
    which all models support. For direct Anthropic: uses ChatAnthropic.
    """
    if config.LLM_PROVIDER == "openrouter":
        from langchain.chat_models import ChatOpenAI
        if not config.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY environment variable not set")
        return ChatOpenAI(
            model=model,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": config.OPENROUTER_SITE_URL,
                "X-Title": config.OPENROUTER_SITE_NAME,
            },
        )
    else:
        from langchain_anthropic import ChatAnthropic
        if not config.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        return ChatAnthropic(
            model=model,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
        )


class BaseAgent(ABC):
    """Base class for all agents"""

    def __init__(
        self,
        name: str,
        description: str,
        data_provider: DataProvider,
        file_storage: FileStorage,
        system_prompt: str = None,
    ):
        self.name = name
        self.description = description
        self.data_provider = data_provider
        self.file_storage = file_storage
        self.system_prompt = system_prompt

        # Initialize LLM
        self.llm = create_llm(config.LLM_MODEL_MAIN)

        # Tools will be registered by subclasses
        self.tools: List[Tool] = []

        # Agent executor (created lazily)
        self._executor = None

    def register_tool(self, tool_func: Callable, name: str = None, description: str = None):
        """Register a tool for this agent"""
        if name is None:
            name = tool_func.__name__
        if description is None:
            description = tool_func.__doc__ or ""

        # LangChain Tool passes Action Input as a single string.
        # Wrap multi-param functions to parse the input string.
        sig = inspect.signature(tool_func)
        params = list(sig.parameters.values())
        required = [p for p in params if p.default == inspect.Parameter.empty
                    and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                   inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        if len(required) > 1:
            orig = tool_func
            def wrapper(input_str: str):
                return _parse_and_call(orig, input_str)
            actual_func = wrapper
        else:
            actual_func = tool_func

        lang_tool = Tool(
            name=name,
            func=actual_func,
            description=description,
        )
        self.tools.append(lang_tool)

    def setup_executor(self):
        """Setup agent executor with optional custom prefix for system prompt."""
        if not self.tools:
            raise ValueError(f"No tools registered for {self.name}")

        prefix = self.system_prompt or ZeroShotAgent.prefix

        # Create agent using ZeroShotAgent (works with old langchain API)
        agent_prompt = ZeroShotAgent.create_prompt(
            tools=self.tools,
            prefix=prefix,
            input_variables=["input", "agent_scratchpad"],
        )
        
        agent = ZeroShotAgent(
            llm_chain=LLMChain(llm=self.llm, prompt=agent_prompt),
            allowed_tools=[tool.name for tool in self.tools],
        )

        # Create executor
        self._executor = AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
        )

    def run(self, input_text: str) -> str:
        """Run agent with input"""
        if self._executor is None:
            self.setup_executor()

        try:
            result = self._executor.run(input=input_text)
            return result
        except Exception as e:
            return f"Agent error: {str(e)}"

    @abstractmethod
    def get_tools(self):
        """Subclasses should implement tool registration"""
        pass
