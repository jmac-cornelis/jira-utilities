##########################################################################################
#
# Module: tools/file_tools.py
#
# Description: File tools for agent use.
#              Provides file I/O operations for reading, writing, and listing files.
#
# Author: Cornelis Networks
#
##########################################################################################

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolResult, tool

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))


# ****************************************************************************************
# Tool Functions
# ****************************************************************************************

@tool(
    description='Read the contents of a file'
)
def read_file(
    file_path: str,
    encoding: str = 'utf-8',
    max_size_mb: float = 10.0
) -> ToolResult:
    '''
    Read the contents of a file.
    
    Input:
        file_path: Path to the file to read.
        encoding: File encoding (default: utf-8).
        max_size_mb: Maximum file size to read in MB.
    
    Output:
        ToolResult with file contents and metadata.
    '''
    log.debug(f'read_file(file_path={file_path})')
    
    try:
        path = Path(file_path)
        
        if not path.exists():
            return ToolResult.failure(f'File not found: {file_path}')
        
        if not path.is_file():
            return ToolResult.failure(f'Not a file: {file_path}')
        
        # Check file size
        size_bytes = path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        
        if size_mb > max_size_mb:
            return ToolResult.failure(
                f'File too large: {size_mb:.2f}MB (max: {max_size_mb}MB)'
            )
        
        # Determine if binary or text
        suffix = path.suffix.lower()
        binary_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.pdf', '.zip', '.tar', '.gz'}
        
        if suffix in binary_extensions:
            return ToolResult.failure(
                f'Binary file type not supported for text reading: {suffix}'
            )
        
        # Read the file
        with open(path, 'r', encoding=encoding) as f:
            content = f.read()
        
        result = {
            'content': content,
            'path': str(path.absolute()),
            'filename': path.name,
            'size_bytes': size_bytes,
            'lines': content.count('\n') + 1,
            'encoding': encoding
        }
        
        return ToolResult.success(result)
        
    except UnicodeDecodeError as e:
        log.error(f'Encoding error reading file: {e}')
        return ToolResult.failure(f'Encoding error: {e}. Try a different encoding.')
    except Exception as e:
        log.error(f'Failed to read file: {e}')
        return ToolResult.failure(f'Failed to read file: {e}')


@tool(
    description='Write content to a file'
)
def write_file(
    file_path: str,
    content: str,
    encoding: str = 'utf-8',
    create_dirs: bool = True,
    overwrite: bool = False
) -> ToolResult:
    '''
    Write content to a file.
    
    Input:
        file_path: Path to the file to write.
        content: Content to write.
        encoding: File encoding (default: utf-8).
        create_dirs: Create parent directories if they don't exist.
        overwrite: Overwrite existing file (default: False for safety).
    
    Output:
        ToolResult confirming write operation.
    '''
    log.debug(f'write_file(file_path={file_path}, overwrite={overwrite})')
    
    try:
        path = Path(file_path)
        
        # Safety check - don't overwrite unless explicitly requested
        if path.exists() and not overwrite:
            return ToolResult.failure(
                f'File already exists: {file_path}. Set overwrite=True to replace.'
            )
        
        # Create parent directories if needed
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.parent.exists():
            return ToolResult.failure(
                f'Parent directory does not exist: {path.parent}'
            )
        
        # Write the file
        with open(path, 'w', encoding=encoding) as f:
            f.write(content)
        
        result = {
            'path': str(path.absolute()),
            'filename': path.name,
            'size_bytes': len(content.encode(encoding)),
            'lines': content.count('\n') + 1,
            'created': not path.exists(),
            'overwritten': path.exists() and overwrite
        }
        
        log.info(f'Wrote file: {file_path}')
        return ToolResult.success(result)
        
    except Exception as e:
        log.error(f'Failed to write file: {e}')
        return ToolResult.failure(f'Failed to write file: {e}')


@tool(
    description='List files and directories in a path'
)
def list_directory(
    dir_path: str = '.',
    pattern: Optional[str] = None,
    recursive: bool = False,
    include_hidden: bool = False
) -> ToolResult:
    '''
    List files and directories.
    
    Input:
        dir_path: Directory path to list (default: current directory).
        pattern: Optional glob pattern to filter (e.g., '*.py').
        recursive: List recursively.
        include_hidden: Include hidden files (starting with .).
    
    Output:
        ToolResult with list of files and directories.
    '''
    log.debug(f'list_directory(dir_path={dir_path}, pattern={pattern})')
    
    try:
        path = Path(dir_path)
        
        if not path.exists():
            return ToolResult.failure(f'Directory not found: {dir_path}')
        
        if not path.is_dir():
            return ToolResult.failure(f'Not a directory: {dir_path}')
        
        files = []
        directories = []
        
        # Get items
        if pattern:
            if recursive:
                items = list(path.rglob(pattern))
            else:
                items = list(path.glob(pattern))
        else:
            if recursive:
                items = list(path.rglob('*'))
            else:
                items = list(path.iterdir())
        
        for item in items:
            # Skip hidden files unless requested
            if not include_hidden and item.name.startswith('.'):
                continue
            
            item_info = {
                'name': item.name,
                'path': str(item.relative_to(path) if recursive else item.name),
                'absolute_path': str(item.absolute())
            }
            
            if item.is_file():
                item_info['size_bytes'] = item.stat().st_size
                item_info['extension'] = item.suffix
                files.append(item_info)
            elif item.is_dir():
                directories.append(item_info)
        
        # Sort by name
        files.sort(key=lambda x: x['name'].lower())
        directories.sort(key=lambda x: x['name'].lower())
        
        result = {
            'path': str(path.absolute()),
            'files': files,
            'directories': directories,
            'file_count': len(files),
            'directory_count': len(directories)
        }
        
        return ToolResult.success(result)
        
    except Exception as e:
        log.error(f'Failed to list directory: {e}')
        return ToolResult.failure(f'Failed to list directory: {e}')


@tool(
    description='Read a JSON file and parse its contents'
)
def read_json(file_path: str) -> ToolResult:
    '''
    Read and parse a JSON file.
    
    Input:
        file_path: Path to the JSON file.
    
    Output:
        ToolResult with parsed JSON data.
    '''
    log.debug(f'read_json(file_path={file_path})')
    
    try:
        result = read_file(file_path)
        if result.is_error:
            return result
        
        content = result.data['content']
        data = json.loads(content)
        
        return ToolResult.success({
            'data': data,
            'path': result.data['path']
        })
        
    except json.JSONDecodeError as e:
        log.error(f'Invalid JSON: {e}')
        return ToolResult.failure(f'Invalid JSON: {e}')
    except Exception as e:
        log.error(f'Failed to read JSON: {e}')
        return ToolResult.failure(f'Failed to read JSON: {e}')


@tool(
    description='Write data to a JSON file'
)
def write_json(
    file_path: str,
    data: Any,
    indent: int = 2,
    overwrite: bool = False
) -> ToolResult:
    '''
    Write data to a JSON file.
    
    Input:
        file_path: Path to the JSON file.
        data: Data to serialize to JSON.
        indent: Indentation level for pretty printing.
        overwrite: Overwrite existing file.
    
    Output:
        ToolResult confirming write operation.
    '''
    log.debug(f'write_json(file_path={file_path})')
    
    try:
        content = json.dumps(data, indent=indent, default=str)
        return write_file(file_path, content, overwrite=overwrite)
        
    except Exception as e:
        log.error(f'Failed to write JSON: {e}')
        return ToolResult.failure(f'Failed to write JSON: {e}')


@tool(
    description='Read a YAML file and parse its contents'
)
def read_yaml(file_path: str) -> ToolResult:
    '''
    Read and parse a YAML file.
    
    Input:
        file_path: Path to the YAML file.
    
    Output:
        ToolResult with parsed YAML data.
    '''
    log.debug(f'read_yaml(file_path={file_path})')
    
    try:
        import yaml
    except ImportError:
        return ToolResult.failure('PyYAML not installed. Run: pip install pyyaml')
    
    try:
        result = read_file(file_path)
        if result.is_error:
            return result
        
        content = result.data['content']
        data = yaml.safe_load(content)
        
        return ToolResult.success({
            'data': data,
            'path': result.data['path']
        })
        
    except yaml.YAMLError as e:
        log.error(f'Invalid YAML: {e}')
        return ToolResult.failure(f'Invalid YAML: {e}')
    except Exception as e:
        log.error(f'Failed to read YAML: {e}')
        return ToolResult.failure(f'Failed to read YAML: {e}')


# ****************************************************************************************
# Tool Collection Class
# ****************************************************************************************

class FileTools(BaseTool):
    '''
    Collection of file tools for agent use.
    '''
    
    @tool(description='Read a file')
    def read_file(self, file_path: str) -> ToolResult:
        return read_file(file_path)
    
    @tool(description='Write to a file')
    def write_file(
        self,
        file_path: str,
        content: str,
        overwrite: bool = False
    ) -> ToolResult:
        return write_file(file_path, content, overwrite=overwrite)
    
    @tool(description='List directory contents')
    def list_directory(
        self,
        dir_path: str = '.',
        pattern: Optional[str] = None
    ) -> ToolResult:
        return list_directory(dir_path, pattern)
    
    @tool(description='Read a JSON file')
    def read_json(self, file_path: str) -> ToolResult:
        return read_json(file_path)
    
    @tool(description='Write to a JSON file')
    def write_json(
        self,
        file_path: str,
        data: Any,
        overwrite: bool = False
    ) -> ToolResult:
        return write_json(file_path, data, overwrite=overwrite)
    
    @tool(description='Read a YAML file')
    def read_yaml(self, file_path: str) -> ToolResult:
        return read_yaml(file_path)
