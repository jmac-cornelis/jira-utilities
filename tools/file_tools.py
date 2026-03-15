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
import re
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
    max_size_mb: float = 10.0,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    tail_lines: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> ToolResult:
    '''
    Read the contents of a file.
    
    Input:
        file_path: Path to the file to read.
        encoding: File encoding (default: utf-8).
        max_size_mb: Maximum file size to read in MB.
        start_line: Optional 1-based start line for partial reads.
        end_line: Optional 1-based end line for partial reads.
        tail_lines: Optional number of lines to read from the end of the file.
        max_chars: Optional maximum number of characters to return.
    
    Output:
        ToolResult with file contents and metadata.
    '''
    log.debug(
        f'read_file(file_path={file_path}, start_line={start_line}, '
        f'end_line={end_line}, tail_lines={tail_lines}, max_chars={max_chars})'
    )
    
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
        
        if start_line is not None and start_line < 1:
            return ToolResult.failure('start_line must be >= 1')

        if end_line is not None and end_line < 1:
            return ToolResult.failure('end_line must be >= 1')

        if tail_lines is not None and tail_lines < 1:
            return ToolResult.failure('tail_lines must be >= 1')

        if start_line is not None and end_line is not None and end_line < start_line:
            return ToolResult.failure('end_line must be >= start_line')

        # Read the file
        with open(path, 'r', encoding=encoding) as f:
            content = f.read()

        total_lines = content.count('\n') + 1 if content else 0
        selected_content = content
        selected_start_line = 1 if total_lines else 0
        selected_end_line = total_lines

        if any(value is not None for value in (start_line, end_line, tail_lines)):
            lines = content.splitlines()
            if content.endswith('\n'):
                lines.append('')

            if tail_lines is not None:
                selected_lines = lines[-tail_lines:]
                selected_start_line = max(len(lines) - len(selected_lines) + 1, 1)
                selected_end_line = len(lines)
            else:
                start_idx = (start_line - 1) if start_line is not None else 0
                end_idx = end_line if end_line is not None else len(lines)
                selected_lines = lines[start_idx:end_idx]
                selected_start_line = start_idx + 1 if selected_lines else 0
                selected_end_line = start_idx + len(selected_lines)

            selected_content = '\n'.join(selected_lines)
            if selected_lines and lines and content.endswith('\n') and selected_end_line == len(lines):
                selected_content += '\n'

        truncated = False
        if max_chars is not None and max_chars >= 0 and len(selected_content) > max_chars:
            selected_content = selected_content[:max_chars]
            truncated = True
        
        result = {
            'content': selected_content,
            'path': str(path.absolute()),
            'filename': path.name,
            'size_bytes': size_bytes,
            'lines': total_lines,
            'encoding': encoding,
            'selected_start_line': selected_start_line,
            'selected_end_line': selected_end_line,
            'truncated': truncated,
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
    description='Find a text pattern in files under a directory'
)
def find_in_files(
    pattern: str,
    root: str = '.',
    glob: Optional[str] = None,
    case_sensitive: bool = False,
    limit: int = 100,
    include_hidden: bool = False,
) -> ToolResult:
    '''
    Search for a text pattern in files under a directory.

    Input:
        pattern: Text or regular expression pattern to search for.
        root: Root directory to search.
        glob: Optional glob pattern to filter files (for example, '*.py').
        case_sensitive: Whether the pattern match should be case-sensitive.
        limit: Maximum number of matches to return.
        include_hidden: Include hidden files and directories.

    Output:
        ToolResult with matching file paths, line numbers, and line text.
    '''
    log.debug(
        f'find_in_files(pattern={pattern}, root={root}, glob={glob}, '
        f'case_sensitive={case_sensitive}, limit={limit})'
    )

    try:
        if limit < 1:
            return ToolResult.failure('limit must be >= 1')

        root_path = Path(root)
        if not root_path.exists():
            return ToolResult.failure(f'Root path not found: {root}')
        if not root_path.is_dir():
            return ToolResult.failure(f'Root path is not a directory: {root}')

        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)
        file_iter = root_path.rglob(glob or '*')

        matches = []
        searched_files = 0
        for path in file_iter:
            if not path.is_file():
                continue
            if not include_hidden and any(part.startswith('.') for part in path.relative_to(root_path).parts):
                continue
            if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.pdf', '.zip', '.tar', '.gz'}:
                continue

            searched_files += 1
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    for line_number, line in enumerate(handle, 1):
                        if regex.search(line):
                            matches.append({
                                'path': str(path.relative_to(root_path)),
                                'absolute_path': str(path.absolute()),
                                'line_number': line_number,
                                'line': line.rstrip('\n'),
                            })
                            if len(matches) >= limit:
                                return ToolResult.success(
                                    {
                                        'root': str(root_path.absolute()),
                                        'matches': matches,
                                        'searched_files': searched_files,
                                    }
                                )
            except (UnicodeDecodeError, OSError):
                continue

        return ToolResult.success({
            'root': str(root_path.absolute()),
            'matches': matches,
            'searched_files': searched_files,
        })
    except re.error as e:
        log.error(f'Invalid search pattern: {e}')
        return ToolResult.failure(f'Invalid search pattern: {e}')
    except Exception as e:
        log.error(f'Failed to search files: {e}')
        return ToolResult.failure(f'Failed to search files: {e}')


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
    def read_file(
        self,
        file_path: str,
        encoding: str = 'utf-8',
        max_size_mb: float = 10.0,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        tail_lines: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> ToolResult:
        return read_file(file_path, encoding, max_size_mb, start_line, end_line, tail_lines, max_chars)
    
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
        pattern: Optional[str] = None,
        recursive: bool = False,
        include_hidden: bool = False,
    ) -> ToolResult:
        return list_directory(dir_path, pattern, recursive, include_hidden)

    @tool(description='Find a text pattern in files')
    def find_in_files(
        self,
        pattern: str,
        root: str = '.',
        glob: Optional[str] = None,
        case_sensitive: bool = False,
        limit: int = 100,
        include_hidden: bool = False,
    ) -> ToolResult:
        return find_in_files(pattern, root, glob, case_sensitive, limit, include_hidden)
    
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
