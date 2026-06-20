Read file content. Returns with line numbers (cat -n format).

**Tips:**
- Use `line_offset` and `n_lines` for partial reads
- Max ${MAX_LINES} lines, truncates lines > ${MAX_LINE_LENGTH} chars
- Read multiple files in parallel when possible
- For searching content, prefer Grep tool
