##########################################################################################
#
# Module: llm/litellm_client.py
#
# Description: LiteLLM-based client for external LLM providers.
#              Supports OpenAI, Anthropic, and other providers via LiteLLM.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

from llm.base import BaseLLM, Message, LLMResponse, LLMError

# Load environment variables
load_dotenv()

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Attempt to import litellm
try:
    import litellm
    from litellm import completion
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    log.warning('litellm package not installed. Run: pip install litellm')


class LiteLLMClient(BaseLLM):
    '''
    Client for external LLM providers via LiteLLM.
    
    LiteLLM provides a unified interface to 100+ LLM providers including:
    - OpenAI (gpt-4, gpt-4o, gpt-3.5-turbo)
    - Anthropic (claude-3-opus, claude-3-sonnet, claude-3-haiku)
    - Google (gemini-pro)
    - And many more
    
    Environment Variables:
        OPENAI_API_KEY: API key for OpenAI models.
        ANTHROPIC_API_KEY: API key for Anthropic models.
        (Other provider keys as needed)
    '''
    
    # Models known to support vision
    VISION_MODELS = {
        # OpenAI
        'gpt-4o',
        'gpt-4o-mini',
        'gpt-4-turbo',
        'gpt-4-vision-preview',
        # Anthropic
        'claude-3-opus-20240229',
        'claude-3-sonnet-20240229',
        'claude-3-haiku-20240307',
        'claude-3-5-sonnet-20241022',
        # Google
        'gemini-pro-vision',
        'gemini-1.5-pro',
        'gemini-1.5-flash',
    }
    
    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        **kwargs
    ):
        '''
        Initialize the LiteLLM client.
        
        Input:
            model: Model identifier in LiteLLM format (e.g., 'gpt-4o', 'claude-3-opus').
            api_key: Optional API key override.
            api_base: Optional API base URL override.
            **kwargs: Additional configuration options.
        '''
        if not LITELLM_AVAILABLE:
            raise LLMError(
                'litellm package required. Run: pip install litellm',
                provider='litellm'
            )
        
        super().__init__(model=model, **kwargs)
        
        self.api_key = api_key
        self.api_base = api_base
        
        # Configure litellm settings
        litellm.drop_params = True  # Drop unsupported params instead of erroring
        
        log.info(f'Initialized LiteLLMClient with model={model}')
    
    def chat(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        '''
        Send a chat completion request via LiteLLM.
        
        Input:
            messages: List of Message objects representing the conversation.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Additional parameters passed to the API.
        
        Output:
            LLMResponse containing the model's response.
        
        Raises:
            LLMError: If the API call fails.
        '''
        log.debug(f'Entering chat() with {len(messages)} messages')
        self.validate_messages(messages)
        
        # Convert messages to API format
        api_messages = [msg.to_dict() for msg in messages]
        
        try:
            # Build request parameters
            params = {
                'model': self.model,
                'messages': api_messages,
                'temperature': temperature,
            }
            if max_tokens:
                params['max_tokens'] = max_tokens
            if self.api_key:
                params['api_key'] = self.api_key
            if self.api_base:
                params['api_base'] = self.api_base
            
            # Add any additional kwargs
            params.update(kwargs)
            
            log.debug(f'Sending request via LiteLLM: model={self.model}')
            response = completion(**params)
            
            # Extract response data
            choice = response.choices[0]
            content = choice.message.content or ''
            
            usage = {}
            if response.usage:
                usage = {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens,
                }
            
            log.debug(f'Received response: {len(content)} chars, usage={usage}')
            
            return LLMResponse(
                content=content,
                model=response.model,
                usage=usage,
                raw_response=response,
                finish_reason=choice.finish_reason
            )
            
        except Exception as e:
            log.error(f'LiteLLM API error: {e}')
            raise LLMError(str(e), provider='litellm')
    
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
            **kwargs: Additional parameters passed to the API.
        
        Output:
            LLMResponse containing the model's response.
        
        Raises:
            LLMError: If the API call fails.
            NotImplementedError: If the model doesn't support vision.
        '''
        log.debug(f'Entering chat_with_vision() with {len(messages)} messages, {len(images)} images')
        
        if not self.supports_vision():
            raise NotImplementedError(
                f'Model {self.model} does not support vision. '
                f'Try: gpt-4o, claude-3-opus, or gemini-1.5-pro'
            )
        
        self.validate_messages(messages)
        
        # Build multimodal messages
        api_messages = []
        images_added = False
        
        for msg in messages:
            if msg.role == 'user' and isinstance(msg.content, str) and not images_added:
                # Add images to the first user message
                content_parts = [{'type': 'text', 'text': msg.content}]
                for image_url in images:
                    content_parts.append({
                        'type': 'image_url',
                        'image_url': {'url': image_url}
                    })
                api_messages.append({'role': 'user', 'content': content_parts})
                images_added = True
            else:
                api_messages.append(msg.to_dict())
        
        try:
            params = {
                'model': self.model,
                'messages': api_messages,
                'temperature': temperature,
            }
            if max_tokens:
                params['max_tokens'] = max_tokens
            if self.api_key:
                params['api_key'] = self.api_key
            if self.api_base:
                params['api_base'] = self.api_base
            params.update(kwargs)
            
            log.debug(f'Sending vision request via LiteLLM: model={self.model}')
            response = completion(**params)
            
            choice = response.choices[0]
            content = choice.message.content or ''
            
            usage = {}
            if response.usage:
                usage = {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens,
                }
            
            log.debug(f'Received vision response: {len(content)} chars')
            
            return LLMResponse(
                content=content,
                model=response.model,
                usage=usage,
                raw_response=response,
                finish_reason=choice.finish_reason
            )
            
        except Exception as e:
            log.error(f'LiteLLM vision API error: {e}')
            raise LLMError(str(e), provider='litellm')
    
    def supports_vision(self) -> bool:
        '''
        Check if the current model supports vision/image analysis.
        
        Output:
            True if the model supports vision, False otherwise.
        '''
        # Check if model is in known vision models
        if self.model in self.VISION_MODELS:
            return True
        
        # Check for common vision model naming patterns
        vision_patterns = ['vision', 'gpt-4o', 'gpt-4-turbo', 'claude-3', 'gemini-1.5']
        model_lower = self.model.lower()
        return any(pattern in model_lower for pattern in vision_patterns)
    
    @staticmethod
    def get_provider(model: str) -> str:
        '''
        Determine the provider for a given model.
        
        Input:
            model: Model identifier.
        
        Output:
            Provider name (openai, anthropic, google, etc.)
        '''
        model_lower = model.lower()
        
        if model_lower.startswith('gpt') or model_lower.startswith('o1'):
            return 'openai'
        elif model_lower.startswith('claude'):
            return 'anthropic'
        elif model_lower.startswith('gemini'):
            return 'google'
        elif model_lower.startswith('mistral'):
            return 'mistral'
        elif model_lower.startswith('llama'):
            return 'meta'
        else:
            return 'unknown'
