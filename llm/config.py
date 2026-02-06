##########################################################################################
#
# Module: llm/config.py
#
# Description: LLM configuration and factory functions.
#              Handles model selection, fallback logic, and client instantiation.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

from dotenv import load_dotenv

from llm.base import BaseLLM, LLMError

# Load environment variables
load_dotenv()

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


class LLMProvider(Enum):
    '''Supported LLM providers.'''
    CORNELIS = 'cornelis'
    OPENAI = 'openai'
    ANTHROPIC = 'anthropic'
    LITELLM = 'litellm'  # Generic LiteLLM for any supported provider


@dataclass
class LLMConfig:
    '''
    Configuration for LLM client instantiation.
    
    Attributes:
        provider: The LLM provider to use.
        model: The model identifier.
        api_key: Optional API key override.
        api_base: Optional API base URL override.
        temperature: Default temperature for completions.
        max_tokens: Default max tokens for completions.
        fallback_provider: Provider to use if primary fails.
        fallback_model: Model to use if primary fails.
        vision_provider: Provider to use for vision tasks.
        vision_model: Model to use for vision tasks.
    '''
    provider: LLMProvider = LLMProvider.CORNELIS
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    
    # Fallback configuration
    fallback_enabled: bool = True
    fallback_provider: Optional[LLMProvider] = LLMProvider.OPENAI
    fallback_model: Optional[str] = 'gpt-4o'
    
    # Vision configuration
    vision_provider: Optional[LLMProvider] = None  # None means use primary
    vision_model: Optional[str] = None
    
    # Additional options
    timeout: float = 120.0
    extra_options: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_env(cls) -> 'LLMConfig':
        '''
        Create configuration from environment variables.
        
        Environment Variables:
            DEFAULT_LLM_PROVIDER: Primary provider (cornelis, openai, anthropic).
            CORNELIS_LLM_MODEL: Model for Cornelis provider.
            OPENAI_MODEL: Model for OpenAI provider.
            ANTHROPIC_MODEL: Model for Anthropic provider.
            FALLBACK_ENABLED: Whether to enable fallback (true/false).
            VISION_LLM_PROVIDER: Provider for vision tasks.
            VISION_LLM_MODEL: Model for vision tasks.
        
        Output:
            LLMConfig instance populated from environment.
        '''
        # Parse provider
        provider_str = os.getenv('DEFAULT_LLM_PROVIDER', 'cornelis').lower()
        try:
            provider = LLMProvider(provider_str)
        except ValueError:
            log.warning(f'Unknown provider "{provider_str}", defaulting to cornelis')
            provider = LLMProvider.CORNELIS
        
        # Get model based on provider
        if provider == LLMProvider.CORNELIS:
            model = os.getenv('CORNELIS_LLM_MODEL', 'cornelis-default')
        elif provider == LLMProvider.OPENAI:
            model = os.getenv('OPENAI_MODEL', 'gpt-4o')
        elif provider == LLMProvider.ANTHROPIC:
            model = os.getenv('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')
        else:
            model = os.getenv('LLM_MODEL', 'gpt-4o')
        
        # Parse fallback settings
        fallback_enabled = os.getenv('FALLBACK_ENABLED', 'true').lower() == 'true'
        
        # Parse vision settings
        vision_provider_str = os.getenv('VISION_LLM_PROVIDER', '').lower()
        vision_provider = None
        if vision_provider_str:
            try:
                vision_provider = LLMProvider(vision_provider_str)
            except ValueError:
                log.warning(f'Unknown vision provider "{vision_provider_str}"')
        
        vision_model = os.getenv('VISION_LLM_MODEL')
        
        return cls(
            provider=provider,
            model=model,
            fallback_enabled=fallback_enabled,
            vision_provider=vision_provider,
            vision_model=vision_model,
            timeout=float(os.getenv('LLM_TIMEOUT', '120'))
        )


def get_llm_client(
    config: Optional[LLMConfig] = None,
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None,
    for_vision: bool = False
) -> BaseLLM:
    '''
    Factory function to create an LLM client.
    
    Input:
        config: Optional LLMConfig instance. If not provided, loads from environment.
        provider: Optional provider override.
        model: Optional model override.
        for_vision: If True, use vision-specific configuration.
    
    Output:
        BaseLLM instance configured for the specified provider.
    
    Raises:
        LLMError: If client creation fails.
    '''
    # Load config from environment if not provided
    if config is None:
        config = LLMConfig.from_env()
    
    # Determine provider and model
    if for_vision and config.vision_provider:
        effective_provider = provider or config.vision_provider
        effective_model = model or config.vision_model
    else:
        effective_provider = provider or config.provider
        effective_model = model or config.model
    
    log.debug(f'Creating LLM client: provider={effective_provider}, model={effective_model}')
    
    # Import here to avoid circular imports
    from llm.cornelis_llm import CornelisLLM
    from llm.litellm_client import LiteLLMClient
    
    try:
        if effective_provider == LLMProvider.CORNELIS:
            return CornelisLLM(
                model=effective_model,
                timeout=config.timeout,
                **config.extra_options
            )
        elif effective_provider in (LLMProvider.OPENAI, LLMProvider.ANTHROPIC, LLMProvider.LITELLM):
            return LiteLLMClient(
                model=effective_model,
                api_key=config.api_key,
                api_base=config.api_base,
                **config.extra_options
            )
        else:
            raise LLMError(f'Unknown provider: {effective_provider}')
            
    except LLMError:
        # If fallback is enabled and we're not already using fallback
        if config.fallback_enabled and effective_provider != config.fallback_provider:
            log.warning(f'Primary LLM failed, falling back to {config.fallback_provider}')
            return get_llm_client(
                config=config,
                provider=config.fallback_provider,
                model=config.fallback_model,
                for_vision=for_vision
            )
        raise


def get_vision_client(config: Optional[LLMConfig] = None) -> BaseLLM:
    '''
    Get an LLM client configured for vision tasks.
    
    Input:
        config: Optional LLMConfig instance.
    
    Output:
        BaseLLM instance that supports vision.
    '''
    return get_llm_client(config=config, for_vision=True)
