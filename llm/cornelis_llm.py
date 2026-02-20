##########################################################################################
#
# Module: llm/cornelis_llm.py
#
# Description: Client for Cornelis Networks internal LLM.
#              Uses OpenAI-compatible API with custom base URL.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
import threading
import time as _time
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

from llm.base import BaseLLM, Message, LLMResponse, LLMError

# Load environment variables
load_dotenv()

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Attempt to import openai - will be used for OpenAI-compatible API
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    log.warning('openai package not installed. Run: pip install openai')


class CornelisLLM(BaseLLM):
    '''
    Client for Cornelis Networks internal LLM.
    
    Uses the OpenAI SDK with a custom base URL to connect to the
    internal OpenAI-compatible LLM endpoint.
    
    Environment Variables:
        CORNELIS_LLM_BASE_URL: Base URL for the internal LLM API.
        CORNELIS_LLM_API_KEY: API key for authentication.
        CORNELIS_LLM_MODEL: Default model to use.
    '''
    
    # Models known to support vision on Cornelis infrastructure
    VISION_MODELS = {
        'cornelis-vision',
        'cornelis-multimodal',
        # Add other vision-capable models as they become available
    }
    
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs
    ):
        '''
        Initialize the Cornelis LLM client.
        
        Input:
            model: Model identifier. Defaults to CORNELIS_LLM_MODEL env var.
            base_url: API base URL. Defaults to CORNELIS_LLM_BASE_URL env var.
            api_key: API key. Defaults to CORNELIS_LLM_API_KEY env var.
            **kwargs: Additional configuration options.
        
        Raises:
            LLMError: If required configuration is missing.
        '''
        if not OPENAI_AVAILABLE:
            raise LLMError(
                'openai package required for CornelisLLM. Run: pip install openai',
                provider='cornelis'
            )
        
        # Get configuration from environment or parameters
        self.base_url = base_url or os.getenv('CORNELIS_LLM_BASE_URL')
        self.api_key = api_key or os.getenv('CORNELIS_LLM_API_KEY')
        model = model or os.getenv('CORNELIS_LLM_MODEL', 'cornelis-default')
        
        if not self.base_url:
            raise LLMError(
                'CORNELIS_LLM_BASE_URL environment variable not set',
                provider='cornelis'
            )
        if not self.api_key:
            raise LLMError(
                'CORNELIS_LLM_API_KEY environment variable not set',
                provider='cornelis'
            )
        
        super().__init__(model=model, **kwargs)
        
        # Initialize OpenAI client with custom base URL
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=kwargs.get('timeout', 120.0)
        )
        
        log.info(f'Initialized CornelisLLM with base_url={self.base_url}, model={model}')
    
    def chat(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        '''
        Send a chat completion request to Cornelis LLM.
        
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
            
            # Add any additional kwargs
            params.update(kwargs)
            
            log.debug(f'Sending request to Cornelis LLM: model={self.model}')

            # Run the blocking API call in a background thread so we can
            # emit periodic heartbeat messages on the main thread.
            result_box: Dict[str, Any] = {}

            def _worker():
                try:
                    result_box['response'] = self.client.chat.completions.create(**params)
                except Exception as exc:
                    result_box['error'] = exc

            worker = threading.Thread(target=_worker, daemon=True)
            start = _time.monotonic()
            worker.start()

            heartbeat = 10
            while worker.is_alive():
                worker.join(timeout=heartbeat)
                if worker.is_alive():
                    elapsed = int(_time.monotonic() - start)
                    log.info(f'Still waiting on LLM return... {elapsed} seconds total')

            elapsed_total = _time.monotonic() - start
            log.info(f'LLM returned in {elapsed_total:.1f}s')

            if 'error' in result_box:
                raise result_box['error']

            response = result_box['response']
            
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
            log.error(f'Cornelis LLM API error: {e}')
            raise LLMError(str(e), provider='cornelis')
    
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
                f'Vision-capable models: {self.VISION_MODELS}'
            )
        
        self.validate_messages(messages)
        
        # Build multimodal messages
        # Find the last user message and add images to it
        api_messages = []
        for msg in messages:
            if msg.role == 'user' and isinstance(msg.content, str):
                # Convert to multimodal format with images
                content_parts = [{'type': 'text', 'text': msg.content}]
                for image_url in images:
                    content_parts.append({
                        'type': 'image_url',
                        'image_url': {'url': image_url}
                    })
                api_messages.append({'role': 'user', 'content': content_parts})
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
            params.update(kwargs)
            
            log.debug(f'Sending vision request to Cornelis LLM: model={self.model}')

            # Heartbeat wrapper — same pattern as chat()
            result_box: Dict[str, Any] = {}

            def _worker():
                try:
                    result_box['response'] = self.client.chat.completions.create(**params)
                except Exception as exc:
                    result_box['error'] = exc

            worker = threading.Thread(target=_worker, daemon=True)
            start = _time.monotonic()
            worker.start()

            heartbeat = 10
            while worker.is_alive():
                worker.join(timeout=heartbeat)
                if worker.is_alive():
                    elapsed = int(_time.monotonic() - start)
                    log.info(f'Still waiting on LLM return... {elapsed} seconds total')

            elapsed_total = _time.monotonic() - start
            log.info(f'LLM returned in {elapsed_total:.1f}s')

            if 'error' in result_box:
                raise result_box['error']

            response = result_box['response']
            
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
            log.error(f'Cornelis LLM vision API error: {e}')
            raise LLMError(str(e), provider='cornelis')
    
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
        vision_patterns = ['vision', 'multimodal', 'gpt-4o', 'gpt-4-turbo']
        model_lower = self.model.lower()
        return any(pattern in model_lower for pattern in vision_patterns)
    
    def list_models(self) -> List[str]:
        '''
        List available models on the Cornelis LLM endpoint.
        
        Output:
            List of model identifiers.
        
        Raises:
            LLMError: If the API call fails.
        '''
        try:
            models = self.client.models.list()
            return [model.id for model in models.data]
        except Exception as e:
            log.error(f'Failed to list models: {e}')
            raise LLMError(str(e), provider='cornelis')
