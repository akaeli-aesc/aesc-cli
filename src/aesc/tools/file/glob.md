Find files using glob patterns. Supports `*`, `?`, `**` (recursive).

**Examples:**
- `*.py` - Python files in current dir
- `src/**/*.js` - JS files recursively in src/
- `test_*.py` - Test files

**Avoid:** `**/*.py` (too broad), `node_modules/**` (too large)
