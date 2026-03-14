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
    # New tool wrappers
    list_filters,
    run_filter,
    run_jql_query,
    get_children_hierarchy,
    get_project_versions_tool,
    get_ticket_totals,
    list_dashboards,
    get_dashboard,
    create_dashboard,
    bulk_update_tickets,
    JiraTools,
)
from tools.confluence_tools import (
    search_confluence_pages,
    get_confluence_page,
    create_confluence_page,
    update_confluence_page,
    append_to_confluence_page,
    update_confluence_section,
    list_confluence_children,
    ConfluenceTools,
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
from tools.excel_tools import (
    build_excel_map,
    concat_excel,
    excel_to_csv,
    csv_to_excel,
    diff_excel,
    ExcelTools,
)
from tools.plan_export_tools import (
    plan_to_csv,
    plan_json_to_dict_rows,
    PlanExportTools,
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
    # New Jira tools
    'list_filters',
    'run_filter',
    'run_jql_query',
    'get_children_hierarchy',
    'get_project_versions_tool',
    'get_ticket_totals',
    'list_dashboards',
    'get_dashboard',
    'create_dashboard',
    'bulk_update_tickets',
    'JiraTools',
    # Confluence
    'search_confluence_pages',
    'get_confluence_page',
    'create_confluence_page',
    'update_confluence_page',
    'append_to_confluence_page',
    'update_confluence_section',
    'list_confluence_children',
    'ConfluenceTools',
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
    # Excel
    'build_excel_map',
    'concat_excel',
    'excel_to_csv',
    'csv_to_excel',
    'diff_excel',
    'ExcelTools',
    # Plan Export
    'plan_to_csv',
    'plan_json_to_dict_rows',
    'PlanExportTools',
]
