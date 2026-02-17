##########################################################################################
#
# Module: tools/drawio_tools.py
#
# Description: Draw.io tools for agent use.
#              Wraps drawio_utilities.py functionality and adds org chart parsing.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import unquote
import re

from tools.base import BaseTool, ToolResult, tool

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Import from drawio_utilities.py - reuse existing functionality
try:
    import drawio_utilities
    from drawio_utilities import (
        load_tickets_from_csv,
        create_drawio_xml,
        get_box_color,
        get_stroke_color,
        JIRA_URL,
        LINK_COLORS,
        BOX_FILL_COLORS,
    )
    DRAWIO_UTILS_AVAILABLE = True
except ImportError as e:
    DRAWIO_UTILS_AVAILABLE = False
    log.warning(f'drawio_utilities.py not available: {e}')
    JIRA_URL = 'https://cornelisnetworks.atlassian.net'


# ****************************************************************************************
# Tool Functions
# ****************************************************************************************

@tool(
    description='Parse an org chart from a draw.io file and extract the organizational structure'
)
def parse_org_chart(file_path: str) -> ToolResult:
    '''
    Parse an org chart from a draw.io file.
    
    Extracts the hierarchical structure of people/roles from a draw.io
    organizational chart diagram.
    
    Input:
        file_path: Path to the .drawio file.
    
    Output:
        ToolResult with organizational structure including:
        - nodes: List of people/roles with their properties
        - hierarchy: Parent-child relationships
        - teams: Grouped by team/department if detectable
    '''
    log.debug(f'parse_org_chart(file_path={file_path})')
    
    try:
        if not os.path.exists(file_path):
            return ToolResult.failure(f'File not found: {file_path}')
        
        # Parse the draw.io XML
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # Draw.io files have mxGraphModel containing mxCell elements
        nodes = {}
        edges = []
        
        # Find all cells in the diagram
        for diagram in root.findall('.//diagram'):
            # Decode the diagram content if compressed
            content = diagram.text
            if content:
                # Handle compressed content
                try:
                    import base64
                    import zlib
                    decoded = base64.b64decode(content)
                    decompressed = zlib.decompress(decoded, -15)
                    content = unquote(decompressed.decode('utf-8'))
                    inner_root = ET.fromstring(content)
                except:
                    # Not compressed, try direct parsing
                    inner_root = diagram
            else:
                inner_root = diagram
            
            # Extract cells from mxGraphModel
            for cell in inner_root.findall('.//mxCell'):
                cell_id = cell.get('id', '')
                value = cell.get('value', '')
                parent = cell.get('parent', '')
                source = cell.get('source', '')
                target = cell.get('target', '')
                style = cell.get('style', '')
                
                # Skip root and layer cells
                if cell_id in ('0', '1'):
                    continue
                
                # Check if this is an edge (connection)
                if source and target:
                    edges.append({
                        'id': cell_id,
                        'source': source,
                        'target': target,
                        'style': style
                    })
                elif value:
                    # This is a node (person/role box)
                    # Clean HTML from value
                    clean_value = _strip_html(value)
                    
                    # Try to extract name and title
                    name, title = _parse_org_node(clean_value)
                    
                    nodes[cell_id] = {
                        'id': cell_id,
                        'raw_value': value,
                        'name': name,
                        'title': title,
                        'parent_cell': parent,
                        'style': style
                    }
        
        # Build hierarchy from edges
        hierarchy = {}
        for edge in edges:
            source = edge['source']
            target = edge['target']
            
            # In org charts, typically source is parent, target is child
            # But this can vary - we'll use the edge direction
            if source in nodes and target in nodes:
                if source not in hierarchy:
                    hierarchy[source] = []
                hierarchy[source].append(target)
                
                # Mark the child's manager
                nodes[target]['manager_id'] = source
                nodes[target]['manager_name'] = nodes[source].get('name', '')
        
        # Find root nodes (no manager)
        root_nodes = [
            node_id for node_id, node in nodes.items()
            if 'manager_id' not in node
        ]
        
        # Build team structure
        teams = _build_teams(nodes, hierarchy, root_nodes)
        
        result = {
            'nodes': list(nodes.values()),
            'hierarchy': hierarchy,
            'root_nodes': root_nodes,
            'teams': teams,
            'edge_count': len(edges),
            'node_count': len(nodes)
        }
        
        log.info(f'Parsed org chart: {len(nodes)} nodes, {len(edges)} edges')
        return ToolResult.success(result)
        
    except ET.ParseError as e:
        log.error(f'Failed to parse draw.io XML: {e}')
        return ToolResult.failure(f'Invalid draw.io file format: {e}')
    except Exception as e:
        log.error(f'Failed to parse org chart: {e}')
        return ToolResult.failure(f'Failed to parse org chart: {e}')


@tool(
    description='Extract responsibility mappings from an org chart - who owns what areas'
)
def get_responsibilities(file_path: str) -> ToolResult:
    '''
    Extract responsibility mappings from an org chart.
    
    Analyzes an org chart to determine who is responsible for what areas,
    useful for assigning Jira tickets to the right people.
    
    Input:
        file_path: Path to the .drawio file.
    
    Output:
        ToolResult with responsibility mappings:
        - by_person: Dict mapping person names to their areas
        - by_area: Dict mapping areas to responsible people
        - team_leads: List of team/department leads
    '''
    log.debug(f'get_responsibilities(file_path={file_path})')
    
    # First parse the org chart
    parse_result = parse_org_chart(file_path)
    if parse_result.is_error:
        return parse_result
    
    org_data = parse_result.data
    nodes = org_data['nodes']
    hierarchy = org_data['hierarchy']
    
    by_person = {}
    by_area = {}
    team_leads = []
    
    for node in nodes:
        name = node.get('name', '')
        title = node.get('title', '')
        node_id = node.get('id', '')
        
        if not name:
            continue
        
        # Determine areas of responsibility from title
        areas = _extract_areas_from_title(title)
        
        # Check if this person manages others (is a lead)
        is_lead = node_id in hierarchy and len(hierarchy[node_id]) > 0
        
        by_person[name] = {
            'title': title,
            'areas': areas,
            'is_lead': is_lead,
            'manager': node.get('manager_name', ''),
            'direct_reports': len(hierarchy.get(node_id, []))
        }
        
        # Map areas to people
        for area in areas:
            if area not in by_area:
                by_area[area] = []
            by_area[area].append({
                'name': name,
                'title': title,
                'is_lead': is_lead
            })
        
        if is_lead:
            team_leads.append({
                'name': name,
                'title': title,
                'team_size': len(hierarchy.get(node_id, []))
            })
    
    result = {
        'by_person': by_person,
        'by_area': by_area,
        'team_leads': team_leads
    }
    
    return ToolResult.success(result)


@tool(
    description='Create a draw.io diagram from a Jira ticket hierarchy CSV (wraps drawio_utilities --create-map)'
)
def create_ticket_diagram(
    csv_file: str,
    output_path: str,
    title: Optional[str] = None
) -> ToolResult:
    '''
    Create a draw.io diagram from ticket CSV data.
    
    This wraps the drawio_utilities.py --create-map functionality.
    
    Input:
        csv_file: Path to CSV file from jira_utils --get-related --hierarchy.
        output_path: Path to save the .drawio file.
        title: Optional diagram title.
    
    Output:
        ToolResult with path to created diagram.
    '''
    log.debug(f'create_ticket_diagram(csv_file={csv_file}, output={output_path})')
    
    if not DRAWIO_UTILS_AVAILABLE:
        return ToolResult.failure('drawio_utilities.py is required but not available')
    
    try:
        if not os.path.exists(csv_file):
            # Try adding .csv extension
            if not csv_file.endswith('.csv') and os.path.exists(f'{csv_file}.csv'):
                csv_file = f'{csv_file}.csv'
            else:
                return ToolResult.failure(f'CSV file not found: {csv_file}')
        
        # Load tickets using drawio_utilities function
        tickets = load_tickets_from_csv(csv_file)
        
        if not tickets:
            return ToolResult.failure('No tickets found in CSV file')
        
        # Determine title
        if not title:
            root_ticket = tickets[0].get('key', 'Unknown')
            title = f'Dependency Map: {root_ticket}'
        
        # Generate draw.io XML using drawio_utilities function
        xml_content = create_drawio_xml(tickets, title)
        
        # Write the file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        
        log.info(f'Created ticket diagram: {output_path}')
        return ToolResult.success({
            'path': output_path,
            'ticket_count': len(tickets),
            'title': title
        })
        
    except Exception as e:
        log.error(f'Failed to create ticket diagram: {e}')
        return ToolResult.failure(f'Failed to create diagram: {e}')


@tool(
    description='Create a draw.io diagram from ticket data (programmatic, not from CSV)'
)
def create_diagram_from_tickets(
    tickets: List[Dict[str, Any]],
    output_path: str,
    title: str = 'Ticket Hierarchy'
) -> ToolResult:
    '''
    Create a draw.io diagram from ticket data.
    
    Generates a visual diagram showing ticket relationships,
    useful for visualizing release structures.
    
    Input:
        tickets: List of ticket dictionaries with keys, summaries, and relationships.
        output_path: Path to save the .drawio file.
        title: Diagram title.
    
    Output:
        ToolResult with path to created diagram.
    '''
    log.debug(f'create_diagram_from_tickets(tickets={len(tickets)}, output={output_path})')
    
    try:
        if DRAWIO_UTILS_AVAILABLE:
            # Use drawio_utilities if available
            # Convert tickets to expected format with depth
            formatted_tickets = []
            for i, ticket in enumerate(tickets):
                formatted_tickets.append({
                    'key': ticket.get('key', f'TICKET-{i}'),
                    'summary': ticket.get('summary', ''),
                    'type': ticket.get('type', 'Story'),
                    'status': ticket.get('status', 'Open'),
                    'depth': ticket.get('depth', 0),
                    'link_via': ticket.get('link_via', ''),
                })
            
            xml_content = create_drawio_xml(formatted_tickets, title)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            
            return ToolResult.success({
                'path': output_path,
                'ticket_count': len(tickets),
                'title': title
            })
        
        # Fallback: Build basic draw.io XML manually
        mxfile = ET.Element('mxfile')
        mxfile.set('host', 'cornelis-agent')
        mxfile.set('modified', '')
        mxfile.set('agent', 'Cornelis Agent Pipeline')
        mxfile.set('version', '1.0')
        
        diagram = ET.SubElement(mxfile, 'diagram')
        diagram.set('name', title)
        diagram.set('id', 'ticket-diagram')
        
        graph_model = ET.SubElement(diagram, 'mxGraphModel')
        graph_model.set('dx', '0')
        graph_model.set('dy', '0')
        graph_model.set('grid', '1')
        graph_model.set('gridSize', '10')
        
        root = ET.SubElement(graph_model, 'root')
        
        # Add required root cells
        cell0 = ET.SubElement(root, 'mxCell')
        cell0.set('id', '0')
        
        cell1 = ET.SubElement(root, 'mxCell')
        cell1.set('id', '1')
        cell1.set('parent', '0')
        
        # Create cells for each ticket
        cell_id = 2
        ticket_cells = {}
        
        # Layout parameters
        x_start = 50
        y_start = 50
        box_width = 200
        box_height = 60
        x_spacing = 250
        y_spacing = 100
        
        # Group tickets by type for layout
        epics = [t for t in tickets if t.get('type', '').lower() == 'epic']
        stories = [t for t in tickets if t.get('type', '').lower() == 'story']
        tasks = [t for t in tickets if t.get('type', '').lower() == 'task']
        others = [t for t in tickets if t.get('type', '').lower() not in ('epic', 'story', 'task')]
        
        # Layout epics at top
        for i, ticket in enumerate(epics):
            x = x_start + (i * x_spacing)
            y = y_start
            cell_id = _add_ticket_cell(root, cell_id, ticket, x, y, box_width, box_height, '#E6FFE6')
            ticket_cells[ticket['key']] = str(cell_id - 1)
        
        # Layout stories below epics
        for i, ticket in enumerate(stories):
            x = x_start + (i * x_spacing)
            y = y_start + y_spacing
            cell_id = _add_ticket_cell(root, cell_id, ticket, x, y, box_width, box_height, '#CCE5FF')
            ticket_cells[ticket['key']] = str(cell_id - 1)
        
        # Layout tasks below stories
        for i, ticket in enumerate(tasks):
            x = x_start + (i * x_spacing)
            y = y_start + (2 * y_spacing)
            cell_id = _add_ticket_cell(root, cell_id, ticket, x, y, box_width, box_height, '#FFFFFF')
            ticket_cells[ticket['key']] = str(cell_id - 1)
        
        # Layout others at bottom
        for i, ticket in enumerate(others):
            x = x_start + (i * x_spacing)
            y = y_start + (3 * y_spacing)
            cell_id = _add_ticket_cell(root, cell_id, ticket, x, y, box_width, box_height, '#F5F5F5')
            ticket_cells[ticket['key']] = str(cell_id - 1)
        
        # Add edges for relationships
        for ticket in tickets:
            ticket_key = ticket['key']
            parent_key = ticket.get('parent_key')
            
            if parent_key and parent_key in ticket_cells and ticket_key in ticket_cells:
                edge = ET.SubElement(root, 'mxCell')
                edge.set('id', str(cell_id))
                edge.set('edge', '1')
                edge.set('parent', '1')
                edge.set('source', ticket_cells[parent_key])
                edge.set('target', ticket_cells[ticket_key])
                edge.set('style', 'edgeStyle=orthogonalEdgeStyle;rounded=1;')
                
                geometry = ET.SubElement(edge, 'mxGeometry')
                geometry.set('relative', '1')
                geometry.set('as', 'geometry')
                
                cell_id += 1
        
        # Write the file
        tree = ET.ElementTree(mxfile)
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        
        log.info(f'Created ticket diagram: {output_path}')
        return ToolResult.success({
            'path': output_path,
            'ticket_count': len(tickets),
            'cell_count': cell_id - 2
        })
        
    except Exception as e:
        log.error(f'Failed to create ticket diagram: {e}')
        return ToolResult.failure(f'Failed to create diagram: {e}')


# ****************************************************************************************
# Helper Functions
# ****************************************************************************************

def _strip_html(text: str) -> str:
    '''Remove HTML tags from text.'''
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Decode HTML entities
    clean = clean.replace('&nbsp;', ' ')
    clean = clean.replace('&', '&')
    clean = clean.replace('<', '<')
    clean = clean.replace('>', '>')
    clean = clean.replace('"', '"')
    # Normalize whitespace
    clean = ' '.join(clean.split())
    return clean.strip()


def _parse_org_node(text: str) -> tuple:
    '''
    Parse an org chart node to extract name and title.
    
    Common formats:
    - "John Smith\nSoftware Engineer"
    - "John Smith - Software Engineer"
    - "John Smith (Software Engineer)"
    '''
    if not text:
        return ('', '')
    
    # Try newline separator
    if '\n' in text:
        parts = text.split('\n', 1)
        return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else '')
    
    # Try dash separator
    if ' - ' in text:
        parts = text.split(' - ', 1)
        return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else '')
    
    # Try parentheses
    match = re.match(r'^(.+?)\s*\((.+?)\)\s*$', text)
    if match:
        return (match.group(1).strip(), match.group(2).strip())
    
    # Just return as name
    return (text.strip(), '')


def _build_teams(nodes: Dict, hierarchy: Dict, root_nodes: List) -> List[Dict]:
    '''Build team structure from hierarchy.'''
    teams = []
    
    def build_team(node_id: str, depth: int = 0) -> Dict:
        node = nodes.get(node_id, {})
        team = {
            'lead': node.get('name', ''),
            'title': node.get('title', ''),
            'members': [],
            'depth': depth
        }
        
        for child_id in hierarchy.get(node_id, []):
            child_node = nodes.get(child_id, {})
            if child_id in hierarchy:
                # This child is also a lead, recurse
                sub_team = build_team(child_id, depth + 1)
                teams.append(sub_team)
            else:
                # This is a leaf member
                team['members'].append({
                    'name': child_node.get('name', ''),
                    'title': child_node.get('title', '')
                })
        
        return team
    
    for root_id in root_nodes:
        team = build_team(root_id)
        teams.append(team)
    
    return teams


def _extract_areas_from_title(title: str) -> List[str]:
    '''Extract areas of responsibility from a job title.'''
    if not title:
        return []
    
    areas = []
    title_lower = title.lower()
    
    # Common area keywords
    area_keywords = {
        'software': 'Software',
        'hardware': 'Hardware',
        'firmware': 'Firmware',
        'driver': 'Drivers',
        'kernel': 'Kernel',
        'network': 'Networking',
        'fabric': 'Fabric',
        'asic': 'ASIC',
        'fpga': 'FPGA',
        'test': 'Testing',
        'qa': 'QA',
        'quality': 'QA',
        'devops': 'DevOps',
        'infrastructure': 'Infrastructure',
        'security': 'Security',
        'performance': 'Performance',
        'documentation': 'Documentation',
        'support': 'Support',
        'management': 'Management',
        'architecture': 'Architecture',
        'design': 'Design',
        'verification': 'Verification',
        'validation': 'Validation',
    }
    
    for keyword, area in area_keywords.items():
        if keyword in title_lower:
            areas.append(area)
    
    return areas if areas else ['General']


def _add_ticket_cell(
    root: ET.Element,
    cell_id: int,
    ticket: Dict,
    x: int,
    y: int,
    width: int,
    height: int,
    fill_color: str
) -> int:
    '''Add a ticket cell to the diagram.'''
    cell = ET.SubElement(root, 'mxCell')
    cell.set('id', str(cell_id))
    cell.set('value', f"{ticket['key']}\n{ticket.get('summary', '')[:30]}")
    cell.set('style', f'rounded=1;whiteSpace=wrap;html=1;fillColor={fill_color};')
    cell.set('vertex', '1')
    cell.set('parent', '1')
    
    geometry = ET.SubElement(cell, 'mxGeometry')
    geometry.set('x', str(x))
    geometry.set('y', str(y))
    geometry.set('width', str(width))
    geometry.set('height', str(height))
    geometry.set('as', 'geometry')
    
    return cell_id + 1


# ****************************************************************************************
# Tool Collection Class
# ****************************************************************************************

class DrawioTools(BaseTool):
    '''
    Collection of draw.io tools for agent use.
    Wraps drawio_utilities.py functionality.
    '''
    
    @tool(description='Parse an org chart from a draw.io file')
    def parse_org_chart(self, file_path: str) -> ToolResult:
        return parse_org_chart(file_path)
    
    @tool(description='Extract responsibility mappings from an org chart')
    def get_responsibilities(self, file_path: str) -> ToolResult:
        return get_responsibilities(file_path)
    
    @tool(description='Create a draw.io diagram from ticket CSV (wraps drawio_utilities)')
    def create_ticket_diagram(
        self,
        csv_file: str,
        output_path: str,
        title: Optional[str] = None
    ) -> ToolResult:
        return create_ticket_diagram(csv_file, output_path, title)
    
    @tool(description='Create a draw.io diagram from ticket data')
    def create_diagram_from_tickets(
        self,
        tickets: List[Dict[str, Any]],
        output_path: str,
        title: str = 'Ticket Hierarchy'
    ) -> ToolResult:
        return create_diagram_from_tickets(tickets, output_path, title)
