##########################################################################################
#
# Module: llm
#
# Description: LLM abstraction layer for Cornelis Agent Pipeline.
#              Provides unified interface for internal Cornelis LLM and external models.
#
# Author: Cornelis Networks
#
##########################################################################################

from llm.base import BaseLLM, Message, LLMResponse
from llm.config import LLMConfig, get_llm_client
from llm.cornelis_llm import CornelisLLM
from llm.litellm_client import LiteLLMClient

__all__ = [
    'BaseLLM',
    'Message', 
    'LLMResponse',
    'LLMConfig',
    'get_llm_client',
    'CornelisLLM',
    'LiteLLMClient',
]
