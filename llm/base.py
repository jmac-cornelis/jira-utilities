##########################################################################################
#
# Module: llm/base.py
#
# Description: Abstract base class for LLM clients.
#              Defines the interface that all LLM implementations must follow.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


@dataclass
class Message:
    '''
    Represents a single message in a conversation.
    
    Attributes:
        role: The role of the message sender - 'system', 'user', or 'assistant'.
        content: The message content - either a string or a list of content parts
                 for multimodal messages (text + images).
    '''
    role: str  # system, user, assistant
    content: Union[str, List[Dict[str, Any]]]  # text or multimodal content
    
    def to_dict(self) -> Dict[str, Any]:
        '''Convert message to dictionary format for API calls.'''
        return {
            'role': self.role,
            'content': self.content
        }
    
    @classmethod
    def system(cls, content: str) -> 'Message':
        '''Create a system message.'''
        return cls(role='system', content=content)
    
    @classmethod
    def user(cls, content: str) -> 'Message':
        '''Create a user message.'''
        return cls(role='user', content=content)
    
    @classmethod
    def assistant(cls, content: str) -> 'Message':
        '''Create an assistant message.'''
        return cls(role='assistant', content=content)
    
    @classmethod
    def user_with_image(cls, text: str, image_url: str) -> 'Message':
        '''
        Create a user message with an image.
        
        Input:
            text: The text content of the message.
            image_url: URL or base64 data URI of the image.
        
        Output:
            Message with multimodal content.
        '''
        return cls(
            role='user',
            content=[
                {'type': 'text', 'text': text},
                {'type': 'image_url', 'image_url': {'url': image_url}}
            ]
        )


@dataclass
class LLMResponse:
    '''
    Represents a response from an LLM.
    
    Attributes:
        content: The text content of the response.
        model: The model that generated the response.
        usage: Token usage statistics.
        raw_response: The raw response object from the API.
        finish_reason: Why the model stopped generating - 'stop', 'length', etc.
    '''
    content: str
    model: str
    usage: Dict[str, int] = field(default_factory=dict)
    raw_response: Any = None
    finish_reason: Optional[str] = None
    
    @property
    def prompt_tokens(self) -> int:
        '''Get the number of prompt tokens used.'''
        return self.usage.get('prompt_tokens', 0)
    
    @property
    def completion_tokens(self) -> int:
        '''Get the number of completion tokens used.'''
        return self.usage.get('completion_tokens', 0)
    
    @property
    def total_tokens(self) -> int:
        '''Get the total number of tokens used.'''
        return self.usage.get('total_tokens', 0)


class BaseLLM(ABC):
    '''
    Abstract base class for LLM clients.
    
    All LLM implementations (Cornelis internal, OpenAI, Anthropic, etc.)
    must inherit from this class and implement the abstract methods.
    '''
    
    def __init__(self, model: str, **kwargs):
        '''
        Initialize the LLM client.
        
        Input:
            model: The model identifier to use.
            **kwargs: Additional configuration options.
        '''
        self.model = model
        self.config = kwargs
        log.debug(f'Initialized {self.__class__.__name__} with model={model}')
    
    @abstractmethod
    def chat(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        '''
        Send a chat completion request.
        
        Input:
            messages: List of Message objects representing the conversation.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional model-specific parameters.
        
        Output:
            LLMResponse containing the model's response.
        
        Raises:
            LLMError: If the API call fails.
        '''
        pass
    
    @abstractmethod
    def chat_with_vision(
        self,
        messages: List[Message],
        images: List[str],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        '''
        Send a chat completion request with image analysis.
        
        Input:
            messages: List of Message objects representing the conversation.
            images: List of image URLs or base64 data URIs.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional model-specific parameters.
        
        Output:
            LLMResponse containing the model's response.
        
        Raises:
            LLMError: If the API call fails.
            NotImplementedError: If the model doesn't support vision.
        '''
        pass
    
    @abstractmethod
    def supports_vision(self) -> bool:
        '''
        Check if the model supports vision/image analysis.
        
        Output:
            True if the model supports vision, False otherwise.
        '''
        pass
    
    def validate_messages(self, messages: List[Message]) -> None:
        '''
        Validate a list of messages.
        
        Input:
            messages: List of Message objects to validate.
        
        Raises:
            ValueError: If messages are invalid.
        '''
        if not messages:
            raise ValueError('Messages list cannot be empty')
        
        valid_roles = {'system', 'user', 'assistant'}
        for i, msg in enumerate(messages):
            if msg.role not in valid_roles:
                raise ValueError(f'Invalid role "{msg.role}" at index {i}. Must be one of: {valid_roles}')
            if not msg.content:
                raise ValueError(f'Empty content at index {i}')
    
    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(model={self.model})'


class LLMError(Exception):
    '''
    Exception raised when LLM operations fail.
    '''
    def __init__(self, message: str, provider: str = None, status_code: int = None):
        self.message = message
        self.provider = provider
        self.status_code = status_code
        super().__init__(self.message)
    
    def __str__(self):
        parts = [self.message]
        if self.provider:
            parts.insert(0, f'[{self.provider}]')
        if self.status_code:
            parts.append(f'(status={self.status_code})')
        return ' '.join(parts)
