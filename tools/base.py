##########################################################################################
#
# Module: tools/base.py
#
# Description: Base classes and decorators for agent tools.
#              Provides a consistent interface for tool definition and execution.
#
# Author: Cornelis Networks
#
##########################################################################################

import functools
import inspect
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
from enum import Enum

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class ToolStatus(Enum):
    '''Status of a tool execution.'''
    SUCCESS = 'success'
    ERROR = 'error'
    PENDING = 'pending'


@dataclass
class ToolResult:
    '''
    Result of a tool execution.
    
    Attributes:
        status: The execution status.
        data: The result data (if successful).
        error: Error message (if failed).
        metadata: Additional metadata about the execution.
    '''
    status: ToolStatus
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def success(cls, data: Any, **metadata) -> 'ToolResult':
        '''Create a successful result.'''
        return cls(status=ToolStatus.SUCCESS, data=data, metadata=metadata)
    
    @classmethod
    def failure(cls, error: str, **metadata) -> 'ToolResult':
        '''Create a failed result.'''
        return cls(status=ToolStatus.ERROR, error=error, metadata=metadata)
    
    @property
    def is_success(self) -> bool:
        '''Check if the result is successful.'''
        return self.status == ToolStatus.SUCCESS
    
    @property
    def is_error(self) -> bool:
        '''Check if the result is an error.'''
        return self.status == ToolStatus.ERROR
    
    def to_dict(self) -> Dict[str, Any]:
        '''Convert result to dictionary.'''
        result = {
            'status': self.status.value,
        }
        if self.data is not None:
            result['data'] = self.data
        if self.error:
            result['error'] = self.error
        if self.metadata:
            result['metadata'] = self.metadata
        return result


@dataclass
class ToolParameter:
    '''
    Definition of a tool parameter.
    
    Attributes:
        name: Parameter name.
        type: Parameter type (string, integer, boolean, array, object).
        description: Description of the parameter.
        required: Whether the parameter is required.
        default: Default value if not provided.
        enum: List of allowed values (for enum parameters).
    '''
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None
    
    def to_schema(self) -> Dict[str, Any]:
        '''Convert to JSON schema format.'''
        schema = {
            'type': self.type,
            'description': self.description,
        }
        if self.enum:
            schema['enum'] = self.enum
        if self.default is not None:
            schema['default'] = self.default
        return schema


@dataclass
class ToolDefinition:
    '''
    Definition of a tool for agent use.
    
    Attributes:
        name: Tool name (function name).
        description: Description of what the tool does.
        parameters: List of tool parameters.
        returns: Description of return value.
        func: The actual function to execute.
    '''
    name: str
    description: str
    parameters: List[ToolParameter]
    returns: str
    func: Callable
    
    def to_function_schema(self) -> Dict[str, Any]:
        '''
        Convert to OpenAI function calling schema format.
        
        Output:
            Dictionary in OpenAI function schema format.
        '''
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_schema()
            if param.required:
                required.append(param.name)
        
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': {
                    'type': 'object',
                    'properties': properties,
                    'required': required,
                }
            }
        }
    
    def to_adk_tool(self) -> Dict[str, Any]:
        '''
        Convert to Google ADK tool format.
        
        Output:
            Dictionary in ADK tool format.
        '''
        # ADK uses a similar format to OpenAI function calling
        return self.to_function_schema()


# Type variable for decorated functions
F = TypeVar('F', bound=Callable[..., Any])


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    returns: str = 'ToolResult with operation result',
    parameters: Optional[Dict[str, str]] = None,
) -> Callable[[F], F]:
    '''
    Decorator to mark a function as an agent tool.
    
    This decorator:
    1. Extracts parameter information from type hints and docstring
    2. Wraps the function to return ToolResult
    3. Adds tool metadata for agent registration
    
    Input:
        name: Optional tool name override (defaults to function name).
        description: Optional description override (defaults to docstring).
        returns: Description of return value.
        parameters: Optional dict of {param_name: description} overrides.
                    If provided, these descriptions take precedence over
                    docstring-extracted descriptions.
    
    Usage::
    
        @tool(description='Search for Jira tickets')
        def search_tickets(jql: str, limit: int = 50) -> ToolResult:
            # Search tickets using JQL query.
            pass
    '''
    def decorator(func: F) -> F:
        # Get function metadata
        tool_name = name or func.__name__
        tool_description = description or (func.__doc__ or '').split('\n')[0].strip()
        
        # Extract parameters from signature and type hints
        sig = inspect.signature(func)
        type_hints = getattr(func, '__annotations__', {})
        
        tool_params = []
        for param_name, param in sig.parameters.items():
            if param_name in ('self', 'cls'):
                continue
            
            # Determine parameter type
            hint = type_hints.get(param_name, str)
            param_type = _python_type_to_json_type(hint)
            
            # Check if required (no default value)
            required = param.default == inspect.Parameter.empty
            default = None if required else param.default
            
            # Try to get description: explicit override > docstring > fallback
            if parameters and param_name in parameters:
                param_desc = parameters[param_name]
            else:
                param_desc = _extract_param_description(func.__doc__, param_name)
            
            tool_params.append(ToolParameter(
                name=param_name,
                type=param_type,
                description=param_desc or f'The {param_name} parameter',
                required=required,
                default=default
            ))
        
        # Create tool definition
        tool_def = ToolDefinition(
            name=tool_name,
            description=tool_description,
            parameters=tool_params,
            returns=returns,
            func=func
        )
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> ToolResult:
            log.debug(f'Executing tool: {tool_name}')
            try:
                result = func(*args, **kwargs)
                # If function already returns ToolResult, use it
                if isinstance(result, ToolResult):
                    return result
                # Otherwise wrap in success result
                return ToolResult.success(result)
            except Exception as e:
                log.error(f'Tool {tool_name} failed: {e}')
                return ToolResult.failure(str(e))
        
        # Attach tool definition to wrapper
        wrapper._tool_definition = tool_def
        
        return wrapper
    
    return decorator


def _python_type_to_json_type(python_type: type) -> str:
    '''Convert Python type hint to JSON schema type.'''
    type_map = {
        str: 'string',
        int: 'integer',
        float: 'number',
        bool: 'boolean',
        list: 'array',
        dict: 'object',
        List: 'array',
        Dict: 'object',
    }
    
    # Handle Optional types
    origin = getattr(python_type, '__origin__', None)
    if origin is Union:
        args = getattr(python_type, '__args__', ())
        # Filter out NoneType for Optional
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return _python_type_to_json_type(non_none_args[0])
    
    # Handle List[X], Dict[X, Y], etc.
    if origin in (list, List):
        return 'array'
    if origin in (dict, Dict):
        return 'object'
    
    return type_map.get(python_type, 'string')


def _extract_param_description(docstring: Optional[str], param_name: str) -> Optional[str]:
    '''Extract parameter description from docstring.'''
    if not docstring:
        return None
    
    # Look for parameter in docstring (supports various formats)
    lines = docstring.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        # Check for "param_name: description" or "param_name - description"
        if line.startswith(f'{param_name}:') or line.startswith(f'{param_name} -'):
            return line.split(':', 1)[-1].split('-', 1)[-1].strip()
        # Check for ":param param_name: description"
        if f':param {param_name}:' in line:
            return line.split(f':param {param_name}:')[-1].strip()
    
    return None


class BaseTool(ABC):
    '''
    Abstract base class for tool collections.
    
    Subclasses should implement tool methods and register them
    for agent use.
    '''
    
    def __init__(self):
        '''Initialize the tool collection.'''
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_tools()
    
    def _register_tools(self) -> None:
        '''Register all tool methods in this class.'''
        for name in dir(self):
            if name.startswith('_'):
                continue
            method = getattr(self, name)
            if hasattr(method, '_tool_definition'):
                self._tools[name] = method._tool_definition
                log.debug(f'Registered tool: {name}')
    
    def get_tools(self) -> List[ToolDefinition]:
        '''Get all registered tools.'''
        return list(self._tools.values())
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        '''Get a specific tool by name.'''
        return self._tools.get(name)
    
    def execute(self, name: str, **kwargs) -> ToolResult:
        '''
        Execute a tool by name.
        
        Input:
            name: Tool name to execute.
            **kwargs: Tool parameters.
        
        Output:
            ToolResult from tool execution.
        '''
        tool_def = self._tools.get(name)
        if not tool_def:
            return ToolResult.failure(f'Unknown tool: {name}')
        
        try:
            return tool_def.func(**kwargs)
        except Exception as e:
            log.error(f'Tool execution failed: {name} - {e}')
            return ToolResult.failure(str(e))
    
    def to_function_schemas(self) -> List[Dict[str, Any]]:
        '''Get all tools as OpenAI function schemas.'''
        return [tool.to_function_schema() for tool in self._tools.values()]
