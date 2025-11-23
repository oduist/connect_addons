# Connect CrewAI

CrewAI integration module for Odoo Connect platform. This module enables multi-agent AI orchestration within Odoo.

## Features

- **AI Agents**: Create intelligent agents with specific roles, goals, and backstories
- **Tasks**: Define tasks with clear descriptions and expected outputs
- **Crews**: Organize agents into crews for collaborative work
- **Execution Tracking**: Monitor crew executions and view results
- **Multiple LLM Support**: OpenAI, Anthropic, Google, and local Ollama
- **Tools Integration**: Search, file operations, code interpretation, and more

## Installation

1. Install the required Python dependencies:
```bash
pip install crewai crewai-tools langchain-openai langchain-anthropic langchain-google-genai langchain-community
```

2. Install the module in Odoo:
   - Go to Apps
   - Update Apps List
   - Search for "Connect CrewAI"
   - Click Install

## Configuration

### API Keys

Configure API keys in Connect Settings:
- OpenAI: Set `openai_api_key` parameter
- Anthropic: Set `anthropic_api_key` parameter
- Google: Set `google_api_key` parameter

### Creating Agents

1. Navigate to **Connect > CrewAI > Agents**
2. Click **Create**
3. Fill in:
   - **Name**: Agent identifier
   - **Role**: Agent's role (e.g., "Senior Research Analyst")
   - **Goal**: What the agent aims to achieve
   - **Backstory**: Context and background
   - **LLM Configuration**: Choose provider and model
   - **Tools**: Optional tools the agent can use

### Creating Tasks

1. Navigate to **Connect > CrewAI > Tasks**
2. Click **Create**
3. Fill in:
   - **Name**: Task identifier
   - **Description**: What needs to be done
   - **Expected Output**: What the output should look like
   - **Agent**: Which agent will handle this task

### Creating Crews

1. Navigate to **Connect > CrewAI > Crews**
2. Click **Create**
3. Add agents to the crew
4. Add or create tasks
5. Choose process type:
   - **Sequential**: Tasks run in order
   - **Hierarchical**: Manager coordinates tasks

### Executing Crews

1. Open a crew
2. Click **Execute Crew**
3. Optionally provide input parameters as JSON
4. Click **Execute**
5. View results in the Executions tab

## Available Tools

- `search_tool`: Web search via SerperDev API
- `website_search_tool`: Search specific websites
- `file_read_tool`: Read files from filesystem
- `directory_read_tool`: List directory contents
- `code_interpreter_tool`: Execute Python code

## Example Use Cases

### Research Team
- **Research Agent**: Searches and gathers information
- **Analysis Agent**: Analyzes and synthesizes findings
- **Writer Agent**: Creates reports and summaries

### Content Creation
- **Topic Researcher**: Finds trending topics
- **Content Writer**: Creates engaging content
- **Editor**: Reviews and refines content

### Customer Support
- **Ticket Analyzer**: Categorizes support requests
- **Solution Finder**: Searches knowledge base
- **Response Writer**: Drafts responses

## Dependencies

- `connect` module
- `mail` module
- `crewai` Python package
- `crewai-tools` Python package
- `langchain-*` Python packages

## License

Business Source License - See LICENSE file for details

## Support

For issues and support, contact: support@oduist.com
