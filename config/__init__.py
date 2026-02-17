##########################################################################################
#
# Module: config
#
# Description: Configuration management for Cornelis Agent Pipeline.
#
# Author: Cornelis Networks
#
##########################################################################################

from config.settings import Settings, get_settings

__all__ = [
    'Settings',
    'get_settings',
]
