# Cornelis Agent Pipeline

An AI-powered agent pipeline for automating Jira release planning at Cornelis Networks. Built with Google ADK architecture patterns and supporting custom LLM endpoints.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Agent Pipeline](#agent-pipeline)
- [Tools](#tools)
- [Development](#development)

## Overview

The Cornelis Agent Pipeline automates the process of creating Jira release structures from roadmap documents. Given roadmap slides, org charts, and the current Jira state, the agent:

1. **Analyzes** roadmap documents (PowerPoint, Excel, images)
2. **Examines** current Jira project state
3. **Creates** a release plan with tickets and assignments
4. **Reviews** the plan with human approval
5. **Executes** approved changes in Jira

### Key Features

- **Multi-agent architecture** - Specialized agents for different tasks
- **Human-in-the-loop** - Approval workflow before any Jira modifications
- **Custom LLM support** - Works with Cornelis internal LLM or external providers
- **Session persistence** - Resume interrupted workflows
- **Vision capabilities** - Extract data from images and slides

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Release Planning Orchestrator                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Vision     │  │    Jira      │  │   Planning   │          │
│  │  Analyzer    │  │   Analyst    │  │    Agent     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐                                               │
│  │   Review     │                                               │
│  │    Agent     │                                               │
│  └──────────────┘                                               │
├─────────────────────────────────────────────────────────────────┤
│                         Tools Layer                              │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │ Jira Tools │ │Draw.io Tools│ │Vision Tools│ │ File Tools │   │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                      LLM Abstraction Layer                       │
│  ┌────────────────────┐  ┌────────────────────┐                 │
│  │   Cornelis LLM     │  │   LiteLLM Client   │                 │
│  │  (Internal API)    │  │ (OpenAI/Anthropic) │                 │
│  └────────────────────┘  └────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

- Python 3.9 or higher
- Access to Cornelis Networks Jira instance
- Jira API token
- Access to Cornelis internal LLM (or external LLM API key)

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd cornelis-agent
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Jira credentials
JIRA_EMAIL=your.email@cornelisnetworks.com
JIRA_API_TOKEN=your_api_token
JIRA_URL=https://cornelisnetworks.atlassian.net

# Cornelis internal LLM
CORNELIS_LLM_BASE_URL=http://internal-llm.cornelis.com/v1
CORNELIS_LLM_API_KEY=your_internal_key
CORNELIS_LLM_MODEL=cornelis-default

# External LLM (fallback/vision)
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key

# Provider selection
DEFAULT_LLM_PROVIDER=cornelis
VISION_LLM_PROVIDER=cornelis
FALLBACK_ENABLED=true
```

### LLM Provider Options

| Provider | Use Case | Configuration |
|----------|----------|---------------|
| `cornelis` | Default, internal LLM | `CORNELIS_LLM_*` variables |
| `openai` | GPT-4, GPT-4o | `OPENAI_API_KEY` |
| `anthropic` | Claude models | `ANTHROPIC_API_KEY` |

## Usage

### Command Line Interface

```bash
# Run full release planning workflow
python main.py plan --project PROJ --roadmap slides.pptx --org-chart org.drawio

# Analyze Jira project state
python main.py analyze --project PROJ --quick

# Analyze roadmap files
python main.py vision roadmap.png roadmap.xlsx

# List saved sessions
python main.py sessions --list

# Resume a saved session
python main.py resume --session abc123
```

### Example Workflow

```bash
# 1. Start release planning
python main.py plan \
  --project ENG \
  --roadmap "Q1_Roadmap.pptx" \
  --roadmap "Features.xlsx" \
  --org-chart "Engineering_Org.drawio" \
  --save-session

# Output:
# ============================================================
# CORNELIS RELEASE PLANNING AGENT
# ============================================================
# 
# Project: ENG
# Roadmap files: 2
# Org chart: Engineering_Org.drawio
# 
# Step 1: Analyzing inputs...
# Step 2: Creating release plan...
# Step 3: Presenting plan for review...
# 
# RELEASE PLAN
# ============
# Release: 12.1.0
#   [Epic] Implement new fabric manager interface
#   [Story] Add topology discovery - Fabric - John Smith
#   [Story] Implement health monitoring - Fabric - Jane Doe
# ...
# 
# Session saved: abc123
```

### Programmatic Usage

```python
from agents.orchestrator import ReleasePlanningOrchestrator

# Create orchestrator
orchestrator = ReleasePlanningOrchestrator()

# Run workflow
result = orchestrator.run({
    'project_key': 'ENG',
    'roadmap_files': ['roadmap.pptx'],
    'org_chart_file': 'org.drawio',
    'mode': 'full'
})

if result.success:
    print(result.content)
    
    # Execute approved plan
    orchestrator.execute_approved_plan()
```

## Agent Pipeline

### Orchestrator Agent

Coordinates the end-to-end workflow:
- Manages sub-agents
- Tracks workflow state
- Handles errors and recovery

### Vision Analyzer Agent

Extracts roadmap data from visual documents:
- PowerPoint slides
- Excel spreadsheets
- Images (PNG, JPG)

### Jira Analyst Agent

Analyzes current Jira project state:
- Existing releases
- Component structure
- Team assignments
- Workflow states

### Planning Agent

Creates release structures:
- Maps features to tickets
- Assigns components and owners
- Sets release versions

### Review Agent

Manages human approval:
- Presents plans for review
- Handles modifications
- Executes approved changes

## Tools

### Jira Tools

| Tool | Description |
|------|-------------|
| `get_project_info` | Get project details |
| `get_releases` | List releases/versions |
| `get_release_tickets` | Get tickets for a release |
| `search_tickets` | Run JQL query |
| `create_ticket` | Create new ticket |
| `update_ticket` | Update existing ticket |
| `create_release` | Create new release |
| `link_tickets` | Create ticket links |

### Draw.io Tools

| Tool | Description |
|------|-------------|
| `parse_org_chart` | Extract org structure |
| `get_responsibilities` | Map people to areas |
| `create_ticket_diagram` | Generate ticket diagram |

### Vision Tools

| Tool | Description |
|------|-------------|
| `analyze_image` | Analyze image with vision LLM |
| `extract_roadmap_from_ppt` | Extract from PowerPoint |
| `extract_roadmap_from_excel` | Extract from Excel |

## Development

### Project Structure

```
cornelis-agent/
├── agents/              # Agent definitions
│   ├── orchestrator.py  # Main orchestrator
│   ├── jira_analyst.py  # Jira analysis
│   ├── planning_agent.py # Release planning
│   ├── vision_analyzer.py # Document analysis
│   └── review_agent.py  # Human review
├── llm/                 # LLM abstraction
│   ├── base.py          # Abstract interface
│   ├── cornelis_llm.py  # Internal LLM client
│   ├── litellm_client.py # External LLM client
│   └── config.py        # LLM configuration
├── tools/               # Agent tools
│   ├── jira_tools.py    # Jira operations
│   ├── drawio_tools.py  # Draw.io operations
│   ├── vision_tools.py  # Vision/document tools
│   └── file_tools.py    # File operations
├── state/               # State management
│   ├── session.py       # Session state
│   └── persistence.py   # Storage backends
├── config/              # Configuration
│   ├── settings.py      # App settings
│   └── prompts/         # Agent prompts
├── data/                # Data files
│   ├── templates/       # Ticket templates
│   └── knowledge/       # Product knowledge
├── main.py              # CLI entry point
└── requirements.txt     # Dependencies
```

### Adding New Tools

1. Create tool function with `@tool` decorator:
   ```python
   from tools.base import tool, ToolResult
   
   @tool(description='My new tool')
   def my_tool(param: str) -> ToolResult:
       # Implementation
       return ToolResult.success({'result': 'data'})
   ```

2. Add to tool collection class
3. Register with agent

### Adding New Agents

1. Create agent class extending `BaseAgent`
2. Define instruction prompt
3. Register tools
4. Implement `run()` method

### Testing

```bash
# Run tests
pytest tests/

# Run specific test
pytest tests/test_tools/test_jira_tools.py
```

## Legacy Utilities

The original utilities are preserved and can be used standalone:

- [`jira_utils.py`](jira_utils.py) - Original Jira CLI utility
- [`drawio_utilities.py`](drawio_utilities.py) - Original draw.io utility

## License

Proprietary - Cornelis Networks

## Support

For issues or questions, contact the Engineering Tools team.
