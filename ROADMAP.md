# cc-dump Roadmap

## Features in Progress

### 1. Show front-ellipsed filename for Read tool
Display long file paths in the Read tool output with ellipsis at the beginning (e.g., `...spath/to/file.ts`) to keep the terminal UI cleaner while still showing the full context.

### 2. Virtually render the conversation panel
Implement virtual rendering for the conversation panel to improve performance when dealing with large conversation histories. This will render only visible items rather than the entire history.

### 3. Headers functionality should show HTTP headers
Enhance the 'headers' feature to display HTTP headers in addition to existing functionality.

### 4. Tool use and tool_response should be correlated via colors
Use consistent color coding to visually link tool_use blocks with their corresponding tool_response blocks for easier reading and navigation.

### 5. When using Skill tool, show skill name
Display the skill name prominently when the Skill tool is invoked, making it clear what skill is being executed.

### 6. When using Bash tool, show bash command name and a few args
Display the bash command name and first few arguments in a concise summary when the Bash tool is invoked.

### 7. Show something meaningful for tool results when collapsed
When tool results are collapsed, display a meaningful summary that includes the tool used and key information about the result, rather than just hiding the content.

## Backlog

- Additional performance optimizations
- Enhanced filtering capabilities
- Extended customization options
