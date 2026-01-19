---
name: todo
description: Manage task tracking using markdown checklists in .vibe/plans/todos.md
---

# Todo Skill

Track progress on multi-step tasks using a markdown checklist format.

## Location

Store todos in: `.vibe/plans/todos.md`

## Format

Use standard markdown checkboxes:
- `[ ]` - Pending task
- `[/]` - In progress (custom notation)
- `[x]` - Completed task

## Example

```markdown
# Project Todos

- [x] Set up project structure
- [/] Implement core features
- [ ] Write tests
- [ ] Update documentation
```

## Guidelines

1. **Always include the complete list** - Don't just send updates, include all todos
2. **One in-progress at a time** - Mark tasks `[/]` only when actively working on them
3. **Mark complete immediately** - Change `[/]` to `[x]` right after finishing
4. **Be specific** - Use clear, actionable task names
5. **Hierarchical tasks** - Use indentation for subtasks:

```markdown
- [ ] Implement authentication
  - [x] Create user model
  - [/] Add login endpoint
  - [ ] Add logout endpoint
```

## Reading Existing Todos

If `.vibe/plans/todos.md` exists, read it first before making changes to preserve existing todos.

## Creating New Todos

When creating a new todo list:
1. Create the `.vibe/plans/` directory if needed
2. Write the todos with a `# Project Todos` header
3. Include all tasks with their current status
