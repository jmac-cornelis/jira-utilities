##########################################################################################
#
# Module: agents/vision_analyzer.py
#
# Description: Vision Analyzer Agent for analyzing roadmap slides and images.
#              Extracts release information from visual documents.
#
# Author: Cornelis Networks
#
##########################################################################################

import logging
import os
import sys
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, AgentConfig, AgentResponse
from tools.vision_tools import VisionTools
from tools.file_tools import FileTools

# Logging config - follows jira_utils.py pattern
log = logging.getLogger(os.path.basename(sys.argv[0]))

# Default instruction for the Vision Analyzer agent
VISION_ANALYZER_INSTRUCTION = '''You are a Vision Analyzer Agent specialized in extracting roadmap information from visual documents.

Your role is to:
1. Analyze roadmap slides, images, and documents
2. Extract release names, versions, and timelines
3. Identify features, milestones, and dependencies
4. Structure the extracted information for release planning

When analyzing visual content, look for:
- Version numbers (e.g., 12.0, 12.1, 13.0)
- Quarter/date references (Q1 2024, March 2024)
- Feature names and descriptions
- Milestone markers
- Dependency arrows or relationships
- Team or component assignments

Output your analysis in a structured format with:
- Releases: List of identified releases with versions and dates
- Features: List of features/items with descriptions
- Timeline: Chronological milestones
- Dependencies: Any identified dependencies between items
- Confidence: Your confidence level in the extraction

Be thorough but also note any ambiguities or items that need clarification.
'''


class VisionAnalyzerAgent(BaseAgent):
    '''
    Agent for analyzing roadmap slides and images.
    
    Uses vision LLM capabilities to extract structured information
    from visual documents like PowerPoint slides, images, and PDFs.
    '''
    
    def __init__(self, **kwargs):
        '''
        Initialize the Vision Analyzer agent.
        '''
        config = AgentConfig(
            name='vision_analyzer',
            description='Analyzes roadmap slides and images to extract release information',
            instruction=VISION_ANALYZER_INSTRUCTION
        )
        
        # Initialize with vision and file tools
        vision_tools = VisionTools()
        file_tools = FileTools()
        
        super().__init__(config=config, tools=[vision_tools, file_tools], **kwargs)
    
    def run(self, input_data: Any) -> AgentResponse:
        '''
        Run the vision analysis.
        
        Input:
            input_data: Either a file path string or dict with:
                - file_path: Path to the file to analyze
                - file_type: Optional type hint (image, ppt, excel)
                - focus_areas: Optional list of areas to focus on
        
        Output:
            AgentResponse with extracted roadmap data.
        '''
        log.debug(f'VisionAnalyzerAgent.run()')
        
        # Parse input
        if isinstance(input_data, str):
            file_path = input_data
            file_type = None
            focus_areas = []
        elif isinstance(input_data, dict):
            file_path = input_data.get('file_path', '')
            file_type = input_data.get('file_type')
            focus_areas = input_data.get('focus_areas', [])
        else:
            return AgentResponse.error_response('Invalid input: expected file path or dict')
        
        if not file_path:
            return AgentResponse.error_response('No file path provided')
        
        if not os.path.exists(file_path):
            return AgentResponse.error_response(f'File not found: {file_path}')
        
        # Determine file type if not provided
        if not file_type:
            file_type = self._detect_file_type(file_path)
        
        # Build the analysis request
        focus_str = ''
        if focus_areas:
            focus_str = f'\n\nFocus particularly on: {", ".join(focus_areas)}'
        
        user_input = f'''Analyze the roadmap document at "{file_path}" (type: {file_type}).

Extract all release planning information including:
1. Release versions and their planned dates
2. Features and their descriptions
3. Timeline and milestones
4. Any dependencies or relationships
5. Team or component assignments if visible

{focus_str}

Use the appropriate tool to extract information from this {file_type} file, then provide a structured analysis.'''
        
        return self._run_with_tools(user_input)
    
    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        '''
        Analyze a file directly without LLM orchestration.
        
        This is a faster method that uses tools directly.
        
        Input:
            file_path: Path to the file to analyze.
        
        Output:
            Dictionary with extracted roadmap data.
        '''
        log.debug(f'analyze_file(file_path={file_path})')
        
        if not os.path.exists(file_path):
            return {'error': f'File not found: {file_path}'}
        
        file_type = self._detect_file_type(file_path)
        
        from tools.vision_tools import (
            analyze_image,
            extract_roadmap_from_ppt,
            extract_roadmap_from_excel
        )
        
        result = {
            'file_path': file_path,
            'file_type': file_type,
            'releases': [],
            'features': [],
            'timeline': [],
            'raw_data': None,
            'errors': []
        }
        
        if file_type == 'image':
            # Use vision analysis
            analysis = analyze_image(
                file_path,
                prompt='''Analyze this roadmap image and extract:
1. All version numbers or release names
2. Dates, quarters, or timeline information
3. Feature names and descriptions
4. Any dependencies or relationships

Format your response as structured data.'''
            )
            
            if analysis.is_success:
                result['raw_data'] = analysis.data
                # Parse the LLM response to extract structured data
                result = self._parse_vision_response(result, analysis.data)
            else:
                result['errors'].append(analysis.error)
                
        elif file_type == 'ppt':
            # Use PowerPoint extraction
            extraction = extract_roadmap_from_ppt(file_path)
            
            if extraction.is_success:
                result['raw_data'] = extraction.data
                result['releases'] = extraction.data.get('releases', [])
                result['features'] = extraction.data.get('features', [])
                result['timeline'] = extraction.data.get('timeline', [])
            else:
                result['errors'].append(extraction.error)
                
        elif file_type == 'excel':
            # Use Excel extraction
            extraction = extract_roadmap_from_excel(file_path)
            
            if extraction.is_success:
                result['raw_data'] = extraction.data
                result['releases'] = extraction.data.get('releases', [])
                result['features'] = extraction.data.get('features', [])
                result['timeline'] = extraction.data.get('timeline', [])
            else:
                result['errors'].append(extraction.error)
        else:
            result['errors'].append(f'Unsupported file type: {file_type}')
        
        return result
    
    def analyze_multiple(self, file_paths: List[str]) -> Dict[str, Any]:
        '''
        Analyze multiple files and combine results.
        
        Input:
            file_paths: List of file paths to analyze.
        
        Output:
            Combined dictionary with all extracted data.
        '''
        log.debug(f'analyze_multiple(files={len(file_paths)})')
        
        combined = {
            'files_analyzed': [],
            'releases': [],
            'features': [],
            'timeline': [],
            'errors': []
        }
        
        seen_releases = set()
        seen_features = set()
        
        for file_path in file_paths:
            result = self.analyze_file(file_path)
            
            combined['files_analyzed'].append({
                'path': file_path,
                'type': result.get('file_type'),
                'success': len(result.get('errors', [])) == 0
            })
            
            # Merge releases (deduplicate by version)
            for release in result.get('releases', []):
                version = release.get('version', '')
                if version and version not in seen_releases:
                    seen_releases.add(version)
                    combined['releases'].append(release)
            
            # Merge features (deduplicate by text)
            for feature in result.get('features', []):
                text = feature.get('text', '')[:50]  # Use first 50 chars as key
                if text and text not in seen_features:
                    seen_features.add(text)
                    combined['features'].append(feature)
            
            # Merge timeline
            combined['timeline'].extend(result.get('timeline', []))
            
            # Collect errors
            combined['errors'].extend(result.get('errors', []))
        
        # Sort timeline by date if possible
        combined['timeline'] = self._sort_timeline(combined['timeline'])
        
        return combined
    
    def _detect_file_type(self, file_path: str) -> str:
        '''Detect the type of file based on extension.'''
        ext = os.path.splitext(file_path)[1].lower()
        
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff'}
        ppt_extensions = {'.ppt', '.pptx'}
        excel_extensions = {'.xls', '.xlsx', '.csv'}
        
        if ext in image_extensions:
            return 'image'
        elif ext in ppt_extensions:
            return 'ppt'
        elif ext in excel_extensions:
            return 'excel'
        elif ext == '.pdf':
            return 'pdf'
        else:
            return 'unknown'
    
    def _parse_vision_response(
        self,
        result: Dict[str, Any],
        vision_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        '''
        Parse the vision LLM response to extract structured data.
        
        This attempts to parse the LLM's description to find releases,
        features, and timeline information.
        '''
        description = vision_data.get('description', '')
        
        if not description:
            return result
        
        import re
        
        # Look for version numbers
        version_pattern = re.compile(r'\b(\d+\.\d+(?:\.\d+)?)\b')
        versions = version_pattern.findall(description)
        for v in set(versions):
            result['releases'].append({'version': v, 'source': 'vision'})
        
        # Look for quarter references
        quarter_pattern = re.compile(
            r'\b(Q[1-4]\s*\d{4}|\d{4}\s*Q[1-4])\b',
            re.IGNORECASE
        )
        quarters = quarter_pattern.findall(description)
        for q in quarters:
            result['timeline'].append({'date': q, 'source': 'vision'})
        
        # Look for date references
        date_pattern = re.compile(
            r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b',
            re.IGNORECASE
        )
        dates = date_pattern.findall(description)
        for d in dates:
            result['timeline'].append({'date': d, 'source': 'vision'})
        
        return result
    
    def _sort_timeline(self, timeline: List[Dict]) -> List[Dict]:
        '''Sort timeline items by date.'''
        def parse_date_key(item):
            date_str = item.get('date', '')
            
            # Try to extract year and quarter/month for sorting
            import re
            
            # Q1 2024 format
            match = re.search(r'Q(\d)\s*(\d{4})', date_str, re.IGNORECASE)
            if match:
                quarter = int(match.group(1))
                year = int(match.group(2))
                return (year, quarter * 3)
            
            # 2024 Q1 format
            match = re.search(r'(\d{4})\s*Q(\d)', date_str, re.IGNORECASE)
            if match:
                year = int(match.group(1))
                quarter = int(match.group(2))
                return (year, quarter * 3)
            
            # Month Year format
            months = {
                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
                'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
                'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
            }
            match = re.search(r'([a-z]{3})[a-z]*\s*(\d{4})', date_str, re.IGNORECASE)
            if match:
                month_str = match.group(1).lower()
                year = int(match.group(2))
                month = months.get(month_str, 1)
                return (year, month)
            
            return (9999, 99)  # Unknown dates go to end
        
        return sorted(timeline, key=parse_date_key)
