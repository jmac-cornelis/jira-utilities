##########################################################################################
#
# Module: agents/base.py
#
# Description: Base classes for agent definitions.
#              Provides common functionality for all agents in the pipeline.
#
# Author: Cornelis Networks
#
##########################################################################################

import json
import logging
import os
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path

from llm.base import BaseLLM, Message, LLMResponse
from llm.config import get_llm_client, LLMConfig
from tools.base import BaseTool, ToolDefinition, ToolResult

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


@dataclass
class AgentConfig:
    '''
    Configuration for an agent.
    
    Attributes:
        name: Agent name/identifier.
        description: Description of the agent's purpose.
        instruction: System instruction/prompt for the agent.
        model: Optional specific model to use.
        temperature: LLM temperature setting.
        max_tokens: Maximum tokens for responses.
        max_iterations: Maximum tool-use iterations.
        timeout_seconds: Timeout for agent execution.
    '''
    name: str
    description: str
    instruction: str
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    max_iterations: int = 20
    timeout_seconds: int = 300


@dataclass
class AgentResponse:
    '''
    Response from an agent execution.
    
    Attributes:
        content: The agent's response content.
        tool_calls: List of tool calls made during execution.
        iterations: Number of iterations taken.
        success: Whether the agent completed successfully.
        error: Error message if failed.
        metadata: Additional metadata.
    '''
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def success_response(cls, content: str, **kwargs) -> 'AgentResponse':
        '''Create a successful response.'''
        return cls(content=content, success=True, **kwargs)
    
    @classmethod
    def error_response(cls, error: str, **kwargs) -> 'AgentResponse':
        '''Create an error response.'''
        return cls(content='', success=False, error=error, **kwargs)


class BaseAgent(ABC):
    '''
    Abstract base class for agents.
    
    Provides common functionality for LLM-based agents including:
    - Tool registration and execution
    - Conversation management
    - Iteration control
    '''
    
    def __init__(
        self,
        config: AgentConfig,
        llm: Optional[BaseLLM] = None,
        tools: Optional[List[Union[BaseTool, Callable]]] = None
    ):
        '''
        Initialize the agent.
        
        Input:
            config: Agent configuration.
            llm: Optional LLM client (will create from config if not provided).
            tools: Optional list of tools or tool collections.
        '''
        self.config = config
        self.llm = llm or get_llm_client()
        self.tools: Dict[str, ToolDefinition] = {}
        self.conversation: List[Message] = []
        
        # Register tools
        if tools:
            for tool in tools:
                self.register_tool(tool)
        
        log.info(f'Initialized agent: {config.name}')
    
    def register_tool(self, tool: Union[BaseTool, Callable, ToolDefinition]) -> None:
        '''
        Register a tool for agent use.
        
        Input:
            tool: A BaseTool collection, callable with _tool_definition, or ToolDefinition.
        '''
        if isinstance(tool, BaseTool):
            # Register all tools from the collection
            for tool_def in tool.get_tools():
                self.tools[tool_def.name] = tool_def
                log.debug(f'Registered tool: {tool_def.name}')
        elif hasattr(tool, '_tool_definition'):
            # Single decorated function
            tool_def = tool._tool_definition
            self.tools[tool_def.name] = tool_def
            log.debug(f'Registered tool: {tool_def.name}')
        elif isinstance(tool, ToolDefinition):
            self.tools[tool.name] = tool
            log.debug(f'Registered tool: {tool.name}')
        else:
            log.warning(f'Cannot register tool: {tool}')
    
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        '''Get OpenAI-format function schemas for all registered tools.'''
        return [tool.to_function_schema() for tool in self.tools.values()]
    
    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        '''
        Execute a registered tool.
        
        Input:
            name: Tool name.
            arguments: Tool arguments.
        
        Output:
            ToolResult from tool execution.
        '''
        tool_def = self.tools.get(name)
        if not tool_def:
            return ToolResult.failure(f'Unknown tool: {name}')
        
        log.debug(f'Executing tool: {name} with args: {arguments}')
        try:
            result = tool_def.func(**arguments)
            if isinstance(result, ToolResult):
                return result
            return ToolResult.success(result)
        except Exception as e:
            log.error(f'Tool execution failed: {name} - {e}')
            return ToolResult.failure(str(e))
    
    def reset_conversation(self) -> None:
        '''Reset the conversation history.'''
        self.conversation = []
    
    def add_system_message(self, content: str) -> None:
        '''Add a system message to the conversation.'''
        self.conversation.append(Message.system(content))
    
    def add_user_message(self, content: str) -> None:
        '''Add a user message to the conversation.'''
        self.conversation.append(Message.user(content))
    
    def add_assistant_message(self, content: str) -> None:
        '''Add an assistant message to the conversation.'''
        self.conversation.append(Message.assistant(content))
    
    @abstractmethod
    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the agent with the given input.
        
        Input:
            input_data: Input data for the agent (format depends on agent type).
        
        Output:
            AgentResponse with the agent's result.
        '''
        pass
    
    def _build_messages(self, user_input: str) -> List[Message]:
        '''
        Build the message list for an LLM call.
        
        Input:
            user_input: The user's input message.
        
        Output:
            List of messages including system instruction and conversation history.
        '''
        messages = []
        
        # Add system instruction
        messages.append(Message.system(self.config.instruction))
        
        # Add conversation history
        messages.extend(self.conversation)
        
        # Add current user input
        messages.append(Message.user(user_input))
        
        return messages
    
    def _run_with_tools(
        self,
        user_input: str,
        max_iterations: Optional[int] = None
    ) -> AgentResponse:
        '''
        Run the agent with tool use capability.
        
        This implements a ReAct-style loop where the agent can:
        1. Think about the task
        2. Call tools to gather information or take actions
        3. Observe tool results
        4. Repeat until done or max iterations reached
        
        Input:
            user_input: The user's input/task.
            max_iterations: Override for max iterations.
        
        Output:
            AgentResponse with final result.
        '''
        max_iter = max_iterations or self.config.max_iterations
        tool_calls_made = []
        
        # Build initial messages
        messages = self._build_messages(user_input)
        
        for iteration in range(max_iter):
            log.info(
                f'Agent {self.config.name} — LLM call '
                f'(iteration {iteration + 1}/{max_iter}, '
                f'{len(messages)} messages)'
            )
            
            try:
                # Call LLM with tools.  Heartbeat "Still waiting on LLM
                # return..." messages are emitted by CornelisLLM.chat()
                # itself, so no wrapper thread is needed here.
                response = self.llm.chat(
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    tools=self.get_tool_schemas() if self.tools else None,
                )
                
                # Check if LLM wants to call tools
                # Note: This depends on the LLM response format
                # For OpenAI-compatible APIs, tool calls are in response
                raw_response = response.raw_response
                
                if hasattr(raw_response, 'choices') and raw_response.choices:
                    choice = raw_response.choices[0]
                    
                    # Check for tool calls
                    if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                        # Process tool calls
                        for tool_call in choice.message.tool_calls:
                            tool_name = tool_call.function.name
                            tool_args = {}
                            
                            # Parse arguments
                            if tool_call.function.arguments:
                                import json
                                try:
                                    tool_args = json.loads(tool_call.function.arguments)
                                except json.JSONDecodeError:
                                    tool_args = {}
                            
                            # Execute tool
                            result = self.execute_tool(tool_name, tool_args)
                            
                            tool_calls_made.append({
                                'tool': tool_name,
                                'arguments': tool_args,
                                'result': result.to_dict()
                            })
                            
                            # Add tool result to messages
                            messages.append(Message.assistant(
                                f'Tool call: {tool_name}({tool_args})'
                            ))
                            messages.append(Message.user(
                                f'Tool result: {result.data if result.is_success else result.error}'
                            ))
                        
                        # Continue loop to let LLM process tool results
                        continue
                    
                    # No tool calls - check if we have a final response
                    if choice.finish_reason == 'stop':
                        return AgentResponse.success_response(
                            content=response.content,
                            tool_calls=tool_calls_made,
                            iterations=iteration + 1
                        )
                
                # Default: return the response content
                return AgentResponse.success_response(
                    content=response.content,
                    tool_calls=tool_calls_made,
                    iterations=iteration + 1
                )
                
            except Exception as e:
                log.error(f'Agent iteration failed: {e}')
                return AgentResponse.error_response(
                    error=str(e),
                    tool_calls=tool_calls_made,
                    iterations=iteration + 1
                )
        
        # Max iterations reached
        return AgentResponse.error_response(
            error=f'Max iterations ({max_iter}) reached',
            tool_calls=tool_calls_made,
            iterations=max_iter
        )
    
    # ------------------------------------------------------------------
    # JSON extraction helper — shared by all agent parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_block(text: str) -> Optional[Dict]:
        '''
        Extract the first ```json ... ``` fenced block from LLM output.

        Returns the parsed dict/list, or None if no valid JSON block is found.
        This is the primary parsing strategy for the hybrid two-pass approach:
        prompts instruct the LLM to emit a ```json block, and this helper
        reliably extracts it.  If the LLM omits the block or produces
        malformed JSON, callers fall back to the legacy Markdown regex parser.
        '''
        if not text:
            return None

        # Match ```json ... ``` (case-insensitive language tag)
        match = re.search(r'```(?:json|JSON)\s*\n(.*?)\n```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                log.warning(f'Found ```json block but JSON parse failed: {exc}')

        # Fallback: try to find a bare top-level JSON object in the text
        # (some LLMs omit the fences but still produce valid JSON)
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            start_idx = text.find(start_char)
            if start_idx == -1:
                continue
            # Walk backwards from the end to find the matching close
            end_idx = text.rfind(end_char)
            if end_idx > start_idx:
                candidate = text[start_idx:end_idx + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass  # not valid JSON — skip

        return None

    def load_prompt(self, prompt_name: str) -> str:
        '''
        Load a prompt from the config/prompts directory.
        
        Input:
            prompt_name: Name of the prompt file (without .md extension).
        
        Output:
            Prompt content as string.
        '''
        prompt_path = Path('config/prompts') / f'{prompt_name}.md'
        
        if prompt_path.exists():
            with open(prompt_path, 'r') as f:
                return f.read()
        
        log.warning(f'Prompt file not found: {prompt_path}')
        return ''
    
    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(name={self.config.name})'
