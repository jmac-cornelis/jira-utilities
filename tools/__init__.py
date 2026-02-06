##########################################################################################
#
# Module: tools
#
# Description: Agent tools for Cornelis Agent Pipeline.
#              Provides tool wrappers for Jira, draw.io, vision, and file operations.
#
# Author: Cornelis Networks
#
##########################################################################################

from tools.base import BaseTool, ToolResult, tool
from tools.jira_tools import (
    get_project_info,
    get_releases,
    get_release_tickets,
    search_tickets,
    create_ticket,
    update_ticket,
    create_release,
    link_tickets,
    get_components,
    assign_ticket,
    get_project_workflows,
    get_project_issue_types,
    JiraTools,
)
from tools.drawio_tools import (
    parse_org_chart,
    get_responsibilities,
    create_ticket_diagram,
    DrawioTools,
)
from tools.vision_tools import (
    analyze_image,
    extract_roadmap_from_ppt,
    extract_roadmap_from_excel,
    extract_text_from_image,
    VisionTools,
)
from tools.file_tools import (
    read_file,
    write_file,
    list_directory,
    FileTools,
)

__all__ = [
    # Base
    'BaseTool',
    'ToolResult',
    'tool',
    # Jira
    'get_project_info',
    'get_releases',
    'get_release_tickets',
    'search_tickets',
    'create_ticket',
    'update_ticket',
    'create_release',
    'link_tickets',
    'get_components',
    'assign_ticket',
    'get_project_workflows',
    'get_project_issue_types',
    'JiraTools',
    # Draw.io
    'parse_org_chart',
    'get_responsibilities',
    'create_ticket_diagram',
    'DrawioTools',
    # Vision
    'analyze_image',
    'extract_roadmap_from_ppt',
    'extract_roadmap_from_excel',
    'extract_text_from_image',
    'VisionTools',
    # File
    'read_file',
    'write_file',
    'list_directory',
    'FileTools',
]
