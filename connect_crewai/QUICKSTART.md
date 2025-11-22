# Connect CrewAI - Quick Start Guide

## 🚀 Quick Setup (5 minutes)

### 1. Install Dependencies
```bash
pip install crewai crewai-tools langchain-openai langchain-anthropic langchain-google-genai langchain-community
```

### 2. Install Module in Odoo
1. Go to **Apps** menu
2. Click **Update Apps List**
3. Search for **"Connect CrewAI"**
4. Click **Install**
5. ✅ Check "Install Demo Data" to get example agents/crews

### 3. Configure API Key
1. Go to **Connect → Settings**
2. Find or create parameter `openai_key`
3. Set your OpenAI API key
4. Save

## 🎯 Your First Crew Execution (2 minutes)

### Using Demo Data (Fastest Way)
If you installed with demo data:

1. **Navigate**: Connect → CrewAI → Crews
2. **Open**: "Content Creation Team Demo"
3. **Click**: "Execute Crew" button
4. **Enter Inputs** (JSON format):
   ```json
   {
     "topic": "AI in Healthcare"
   }
   ```
5. **Click**: "Execute"
6. **Wait**: Crew will research and write content
7. **View Results**: Check the result and output fields

### Building Your Own Crew
1. **Create an Agent**:
   - Connect → CrewAI → Agents → Create
   - Name: "My Researcher"
   - Role: "Research Expert"
   - Goal: "Find relevant information on topics"
   - Backstory: "You are an expert researcher"
   - LLM Provider: OpenAI
   - LLM Model: gpt-4o-mini
   - Tools: search_tool

2. **Create a Task**:
   - Connect → CrewAI → Tasks → Create
   - Name: "Research Task"
   - Description: "Research the given topic thoroughly"
   - Expected Output: "A detailed research report"
   - Agent: My Researcher

3. **Create a Crew**:
   - Connect → CrewAI → Crews → Create
   - Name: "My Research Team"
   - Add your agent to Agents tab
   - Add your task to Tasks tab
   - Process: Sequential
   - Save

4. **Execute**:
   - Click "Execute Crew"
   - Add inputs: `{"topic": "Your Topic Here"}`
   - Click Execute
   - View results!

## 💡 Common Use Cases

### Research & Writing
**Agents**: Researcher + Writer + Editor
**Tasks**: Research → Write → Edit
**Input**: `{"topic": "AI Ethics", "tone": "professional"}`

### Market Analysis
**Agents**: Data Collector + Analyst + Report Writer
**Tasks**: Collect Data → Analyze → Write Report
**Input**: `{"company": "TechCorp", "competitors": ["CompA", "CompB"]}`

### Content Creation
**Agents**: Topic Researcher + Content Creator + SEO Expert
**Tasks**: Find Topics → Create Content → Optimize SEO
**Input**: `{"industry": "Technology", "keywords": ["AI", "automation"]}`

## 🔧 Configuration Options

### Agent Settings
- **Temperature**: 0.0 = Focused, 2.0 = Creative
- **Verbose**: Enable to see detailed logs
- **Allow Delegation**: Let agent delegate tasks to others
- **Tools**: Comma-separated: `search_tool, file_read_tool`

### Crew Settings
- **Process**: 
  - Sequential: Tasks run in order
  - Hierarchical: Manager coordinates (requires Manager LLM)
- **Memory**: Enable for agents to remember context
- **Cache**: Speed up repeated operations

### Available Tools
- `search_tool` - Web search
- `website_search_tool` - Search specific sites
- `file_read_tool` - Read files
- `directory_read_tool` - List directories
- `code_interpreter_tool` - Run Python code

## 📊 Monitoring Executions

1. **View All Executions**: Connect → CrewAI → Executions
2. **View Crew Executions**: Open Crew → Click "View Executions"
3. **Check Status**: 
   - 🟢 Done: Successful
   - 🔴 Error: Failed (check error message)
   - 🔵 Running: In progress
   - ⚪ Draft: Not started

4. **Track Metrics**:
   - Duration: How long it took
   - Token Usage: Cost estimation
   - Full Output: Complete logs

## ❓ Troubleshooting

### "OpenAI API key not configured"
→ Set `openai_key` in Connect Settings

### "CrewAI library is not installed"
→ Run: `pip install crewai crewai-tools`

### "Tool import error"
→ Some tools need extra setup (e.g., SerperDev API for search_tool)

### Execution takes too long
→ Increase `max_execution_time` in agent settings

### Want faster responses
→ Use gpt-4o-mini instead of gpt-4o

## 🎓 Learning Resources

- **CrewAI Docs**: https://docs.crewai.com
- **Example Crews**: See demo data for patterns
- **Agent Prompting**: Clear roles and goals = better results
- **Task Design**: Specific descriptions = better outputs

## 💰 Cost Management

### Token Usage Tips
1. Use gpt-4o-mini for development/testing
2. Use gpt-4o for production when needed
3. Monitor token usage in execution records
4. Set max_tokens to limit responses
5. Use cache=True to avoid re-computation

### Recommended Models by Use Case
- **Quick tasks**: gpt-4o-mini ($0.15/1M tokens)
- **Complex reasoning**: gpt-4o ($2.50/1M tokens)
- **Budget option**: gpt-3.5-turbo ($0.50/1M tokens)
- **Free option**: Ollama (local, requires setup)

## 🚀 Next Steps

1. ✅ Installed and configured
2. ✅ Executed demo crew
3. 📝 Create your first custom agent
4. 📝 Design a multi-agent workflow
5. 📝 Integrate with your business process
6. 📝 Set up scheduled executions (future feature)

## 📞 Support

- **Email**: support@oduist.com
- **Documentation**: See README.md and SUMMARY.md
- **Demo Data**: Great learning examples

---

**Pro Tip**: Start simple! Create one agent with one task, then expand. The demo crew is a great template to learn from.
