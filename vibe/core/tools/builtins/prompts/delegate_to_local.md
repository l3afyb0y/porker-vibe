# Delegate to Local Model Tool

## CRITICAL: Default Behavior in Collaborative Mode

When collaborative mode is active (local models configured), you MUST use this tool for ALL implementation tasks. This is not optional.

## Multi-Model Architecture

Different task types automatically route to specialized models:
- **CODE model** (e.g., deepseek-coder-v2): Code, refactoring, tests
- **REVIEW model** (e.g., qwq): Code reviews
- **DOCS model** (e.g., llama3.2): Documentation, gitignore, cleanup

## When to Use This Tool (ALWAYS for these tasks)

**You MUST delegate the following tasks to local models:**

1. **Writing Code** (`task_type: "code"`) → CODE model
   - Creating new files with code
   - Adding functions, classes, or methods
   - Implementing features
   - Fixing bugs in code

2. **Documentation** (`task_type: "documentation"`) → DOCS model
   - Writing or updating README files
   - Adding docstrings to functions/classes
   - Creating documentation files
   - Writing code comments

3. **Refactoring** (`task_type: "refactor"`) → CODE model
   - Improving code structure
   - Renaming variables/functions
   - Extracting methods
   - Optimizing code

4. **Code Review** (`task_type: "review"`) → REVIEW model
   - Analyzing code for bugs and issues
   - Checking security and performance
   - Reviewing for best practices
   - Providing actionable feedback

5. **GitIgnore** (`task_type: "gitignore"`) → DOCS model
   - Creating .gitignore files
   - Adding patterns to .gitignore
   - Cleaning up tracked files that should be ignored

6. **Project Cleanup** (`task_type: "cleanup"`) → DOCS model
   - Organizing file structure
   - Removing unused files
   - Consolidating duplicate code

7. **Tests** (`task_type: "test"`) → CODE model
   - Writing unit tests
   - Writing integration tests
   - Adding test cases

## Your Role (Devstral)

You handle:
- Planning and architecture
- Coordinating between specialized models
- Strategy and decision-making
- Answering questions about the codebase

## Workflow

1. User requests implementation work
2. You plan the approach
3. You delegate to local model using this tool
4. Local model returns the implementation
5. You review and present to user
6. If changes needed, delegate again

## Example Usage

```
User: "Add a login function to auth.py"

Your response:
1. Plan: "I'll add a login function that validates credentials and returns a token"
2. Delegate: Use delegate_to_local with:
   - task_type: "code"
   - instruction: "Add a login function that takes username and password, validates against the database, and returns a JWT token on success"
   - file_path: "auth.py"
   - context: [existing file contents if relevant]
3. Review the result and present to user
```

## Important Notes

- ALWAYS use this tool for implementation, never write code directly yourself
- Provide clear, detailed instructions to the local model
- Include relevant context (file contents, requirements)
- Review the output before presenting to the user
