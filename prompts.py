def get_gem_context_prompt(codebase):
    template = """Act as an AI System Architect. I am providing you with the minified source code of my entire application.
Your task is to generate a master `AI_GEM_CONTEXT.md` file. I will use this file as the "System Instructions" for a custom AI coding assistant.

The document MUST be extremely dense and structured for another LLM to read efficiently.
Include these exact sections:

### 🏗️ Architecture & Stack
(Define the framework, frontend, backend, and API patterns used)

### 🗄️ Database & Schema Overview
(List the core entities, their relationships, and multi-tenancy rules if any exist)

### 🚀 Core Business Logic
(Summarize the primary purpose of the application based on the controllers/services)

### 🧠 Coding Conventions & Rules
(Identify how routing, validation, Vue compositions, and API responses are handled so the Gem knows how to format its code)

CODEBASE:
[CODEBASE_CONTENT]
"""
    return template.replace("[CODEBASE_CONTENT]", codebase)


def get_audit_prompt(codebase):
    template = """Act as a Senior Application Security and Performance Engineer. Review this codebase and output a Markdown report.
1. Identify any N+1 query problems in the Controllers/Models.
2. Identify any mass-assignment vulnerabilities or missing validation.
3. Highlight architectural anti-patterns (e.g. business logic in routes/views).

CODEBASE:
[CODEBASE_CONTENT]
"""
    return template.replace("[CODEBASE_CONTENT]", codebase)


def get_erd_prompt(codebase):
    template = """Act as a Database Architect. Analyze these Laravel Models and Migrations.
Generate a comprehensive Entity-Relationship Diagram using Mermaid.js syntax.
Return ONLY the markdown block starting with ```mermaid and ending with ```.
Use `erDiagram` syntax. Include cardinality (e.g., one-to-many, zero-to-many).

CRITICAL MERMAID RULES:
1. Define tables EXACTLY like this:
   TABLE_NAME {
       string column_name PK
       int reference_id FK
       string basic_column
   }
2. STRICT RULE: For column constraints, you may ONLY use "PK" or "FK". DO NOT use "UK", "unique", or any other modifiers.
3. STRICT RULE: Every closing brace `}` MUST be followed by a newline. Do not jam tables together.
4. Entity names must be alphanumeric without spaces.

CODEBASE:
[CODEBASE_CONTENT]
"""
    return template.replace("[CODEBASE_CONTENT]", codebase)


def get_context_prompt(rel_path, filename, code_content):
    template = """Perform an engineering analysis of the following code from `[REL_PATH]`.
Provide the response STRICTLY in Markdown using the following exact structure.

### 📄 System Overview
(Provide a 1-2 sentence architectural summary of what this file does.)

### ⚙️ Functional Specifications
(Create a Markdown TABLE detailing the functions. Use these columns: `Method/Function`, `Visibility`, `Purpose`, `Core Mechanics/Logic`)

### 🔗 Dependency Architecture
(Provide a Mermaid.js graph showing how this file connects to others. Wrap it exactly in a ```mermaid code block. Show `[FILENAME]` in the center.
CRITICAL MERMAID RULES:
1. ALWAYS place a newline after `graph TD` or `graph LR`.
2. Node IDs must be alphanumeric ONLY, NO SPACES (e.g. NodeA, NodeB).
3. For labels with spaces/symbols, use brackets (e.g. NodeA["My Label (Vue)"]).)

### 💡 Engineering Remarks & Optimizations
(Review the code and provide 2-3 bullet points suggesting refactors, security improvements, or best practices.)

CODE:
[CODE_CONTENT]
"""
    return (
        template
        .replace("[REL_PATH]", rel_path)
        .replace("[FILENAME]", filename)
        .replace("[CODE_CONTENT]", code_content)
    )


def get_chat_prompt(message, mode, selected_paths, selected_code, project_state, history):
    history_block = _render_history(history)
    selected_paths_block = "\n".join(f"- {path}" for path in selected_paths) if selected_paths else "- None"

    template = """You are Nexus Copilot inside the Nexus dashboard.

Operating rules:
1. Be direct.
2. Prefer small maintainable changes.
3. Avoid god components and giant rewrites.
4. When suggesting code structure, break work into bite-sized files/services.
5. If selected files are provided, ground your answer in them first.
6. If the user asks for implementation, return full code only.

Current mode:
[MODE]

Project state:
[PROJECT_STATE]

Selected files:
[SELECTED_PATHS]

Conversation history:
[HISTORY]

Selected file contents:
[SELECTED_CODE]

User message:
[USER_MESSAGE]
"""
    return (
        template
        .replace("[MODE]", mode)
        .replace("[PROJECT_STATE]", project_state)
        .replace("[SELECTED_PATHS]", selected_paths_block)
        .replace("[HISTORY]", history_block)
        .replace("[SELECTED_CODE]", selected_code or "No files selected.")
        .replace("[USER_MESSAGE]", message)
    )


def _render_history(history):
    if not history:
        return "No previous conversation."

    blocks = []
    for item in history[-10:]:
        role = item.get("role", "unknown").upper()
        content = item.get("content", "")
        blocks.append(f"{role}:\n{content}")

    return "\n\n".join(blocks)
