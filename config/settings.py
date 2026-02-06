##########################################################################################
#
# Module: config/settings.py
#
# Description: Application settings and configuration management.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


@dataclass
class Settings:
    '''
    Application settings loaded from environment variables.
    '''
    # Jira settings
    jira_url: str = 'https://cornelisnetworks.atlassian.net'
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None
    
    # Cornelis LLM settings
    cornelis_llm_base_url: Optional[str] = None
    cornelis_llm_api_key: Optional[str] = None
    cornelis_llm_model: str = 'cornelis-default'
    
    # External LLM settings
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    
    # LLM configuration
    default_llm_provider: str = 'cornelis'
    vision_llm_provider: str = 'cornelis'
    fallback_enabled: bool = True
    
    # Agent configuration
    agent_log_level: str = 'INFO'
    agent_max_iterations: int = 50
    agent_timeout_seconds: int = 300
    
    # State persistence
    state_persistence_enabled: bool = True
    state_persistence_path: str = './data/sessions'
    state_persistence_format: str = 'json'  # json, sqlite, both
    
    # Logging
    log_file: str = 'cornelis_agent.log'
    log_level: str = 'DEBUG'
    
    @classmethod
    def from_env(cls) -> 'Settings':
        '''
        Create settings from environment variables.
        
        Output:
            Settings instance populated from environment.
        '''
        return cls(
            # Jira
            jira_url=os.getenv('JIRA_URL', 'https://cornelisnetworks.atlassian.net'),
            jira_email=os.getenv('JIRA_EMAIL'),
            jira_api_token=os.getenv('JIRA_API_TOKEN'),
            
            # Cornelis LLM
            cornelis_llm_base_url=os.getenv('CORNELIS_LLM_BASE_URL'),
            cornelis_llm_api_key=os.getenv('CORNELIS_LLM_API_KEY'),
            cornelis_llm_model=os.getenv('CORNELIS_LLM_MODEL', 'cornelis-default'),
            
            # External LLM
            openai_api_key=os.getenv('OPENAI_API_KEY'),
            anthropic_api_key=os.getenv('ANTHROPIC_API_KEY'),
            
            # LLM config
            default_llm_provider=os.getenv('DEFAULT_LLM_PROVIDER', 'cornelis'),
            vision_llm_provider=os.getenv('VISION_LLM_PROVIDER', 'cornelis'),
            fallback_enabled=os.getenv('FALLBACK_ENABLED', 'true').lower() == 'true',
            
            # Agent config
            agent_log_level=os.getenv('AGENT_LOG_LEVEL', 'INFO'),
            agent_max_iterations=int(os.getenv('AGENT_MAX_ITERATIONS', '50')),
            agent_timeout_seconds=int(os.getenv('AGENT_TIMEOUT_SECONDS', '300')),
            
            # State persistence
            state_persistence_enabled=os.getenv('STATE_PERSISTENCE_ENABLED', 'true').lower() == 'true',
            state_persistence_path=os.getenv('STATE_PERSISTENCE_PATH', './data/sessions'),
            state_persistence_format=os.getenv('STATE_PERSISTENCE_FORMAT', 'json'),
            
            # Logging
            log_file=os.getenv('LOG_FILE', 'cornelis_agent.log'),
            log_level=os.getenv('LOG_LEVEL', 'DEBUG'),
        )
    
    def validate(self) -> bool:
        '''
        Validate that required settings are present.
        
        Output:
            True if all required settings are valid.
        
        Raises:
            ValueError: If required settings are missing.
        '''
        errors = []
        
        # Check Jira credentials
        if not self.jira_email:
            errors.append('JIRA_EMAIL is required')
        if not self.jira_api_token:
            errors.append('JIRA_API_TOKEN is required')
        
        # Check LLM credentials based on provider
        if self.default_llm_provider == 'cornelis':
            if not self.cornelis_llm_base_url:
                errors.append('CORNELIS_LLM_BASE_URL is required for cornelis provider')
            if not self.cornelis_llm_api_key:
                errors.append('CORNELIS_LLM_API_KEY is required for cornelis provider')
        elif self.default_llm_provider == 'openai':
            if not self.openai_api_key:
                errors.append('OPENAI_API_KEY is required for openai provider')
        elif self.default_llm_provider == 'anthropic':
            if not self.anthropic_api_key:
                errors.append('ANTHROPIC_API_KEY is required for anthropic provider')
        
        if errors:
            for error in errors:
                log.error(f'Configuration error: {error}')
            raise ValueError(f'Configuration errors: {", ".join(errors)}')
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        '''Convert settings to dictionary (masking sensitive values).'''
        return {
            'jira_url': self.jira_url,
            'jira_email': self.jira_email,
            'jira_api_token': '***' if self.jira_api_token else None,
            'cornelis_llm_base_url': self.cornelis_llm_base_url,
            'cornelis_llm_api_key': '***' if self.cornelis_llm_api_key else None,
            'cornelis_llm_model': self.cornelis_llm_model,
            'openai_api_key': '***' if self.openai_api_key else None,
            'anthropic_api_key': '***' if self.anthropic_api_key else None,
            'default_llm_provider': self.default_llm_provider,
            'vision_llm_provider': self.vision_llm_provider,
            'fallback_enabled': self.fallback_enabled,
            'agent_max_iterations': self.agent_max_iterations,
            'state_persistence_enabled': self.state_persistence_enabled,
            'state_persistence_format': self.state_persistence_format,
        }


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    '''
    Get the global settings instance.
    
    Output:
        Settings instance (creates from environment if not exists).
    '''
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def configure_logging(settings: Optional[Settings] = None) -> None:
    '''
    Configure logging based on settings.
    
    Input:
        settings: Optional settings instance (uses global if not provided).
    '''
    settings = settings or get_settings()
    
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))
    
    # File handler
    fh = logging.FileHandler(settings.log_file, mode='w')
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s'
    )
    fh.setFormatter(formatter)
    root_logger.addHandler(fh)
    
    # Console handler for warnings and above
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, settings.agent_log_level.upper()))
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    root_logger.addHandler(ch)
    
    log.info(f'Logging configured: file={settings.log_file}, level={settings.log_level}')
