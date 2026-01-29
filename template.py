##########################################################################################
#
# Script name: template.py
#
# Description: This is a template for a Python script.
#
# Author: John Macdonald
#
##########################################################################################

import argparse
import logging
import sys
import os
from datetime import date
import re

# ****************************************************************************************
# Global data and configuration
# ****************************************************************************************
# Set global variables here and log.debug them below

# Logging config
log = logging.getLogger(os.path.basename(sys.argv[0]))
log.setLevel(logging.DEBUG)

# File handler for logging
fh = logging.FileHandler('churchdb.log', mode='w')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s')
fh.setFormatter(formatter)
log.addHandler(fh)  # Add file handler to logger                

log.debug(f'Global data and configuration for this script...')


# ****************************************************************************************
# Exceptions
# ****************************************************************************************

class Error(Exception):
    '''
    Base class for exceptions in this module.
    '''
    pass

class RequestError(Error):
    '''
    Base class for exceptions in this module.
    '''
    def __init__(self, url):
        self.message = f"Failed to fetch URL: {url}"
        super().__init__(self.message)

# ****************************************************************************************
# Functions
# ****************************************************************************************


    
# ****************************************************************************************
# Handle the arguments
# ****************************************************************************************
def handle_args():
    '''
    Parse CLI arguments and configure console logging handlers.

    Input:
        None directly; reads flags from sys.argv.

    Output:
        argparse.Namespace containing boolean flags `verbose` and `quiet` that
        determine runtime logging levels.

    Side Effects:
        Attaches a stream handler to the module logger with formatting and
        level derived from the parsed arguments.
    '''
    
    parser = argparse.ArgumentParser(description='ChurchDB utilities')
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='Enable verbose output to stdout.')
    parser.add_argument(
        '-q',
        '--quiet',
        action='store_true',
        help='Minimal stdout.')
    args = parser.parse_args()

    # Configure stdout logging based on arguments
    ch = logging.StreamHandler(sys.stdout)
    if args.verbose:
        ch.setLevel(logging.DEBUG)
    elif args.quiet:
        ch.setLevel(logging.ERROR)
    else:
        ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    log.addHandler(ch)
    
    log.debug(f'Checking script requirements...')
    # Check requirements to execute the script here
    if not args.verbose and not args.quiet:
        log.debug('No output level specified. Defaulting to INFO.')
    # More requirements?

    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    log.info(f'+  {os.path.basename(sys.argv[0])}')
    log.info(f'+  Python Version: {sys.version.split()[0]}')
    log.info(f'+  Today is: {date.today()}')
    # log.info important input vars and output args
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')        

    return args

# ****************************************************************************************
# Main
# ****************************************************************************************
def main():
    '''
    Entrypoint that wires together dependencies and launches the CLI loop.

    Sequence:
        

    Output:
        
    '''
    args = handle_args()

if __name__ == '__main__':
    main()
