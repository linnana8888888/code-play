---
name: Coding Standards
description: Code style and quality guidelines for the game studio
---

# Coding Standards

## JavaScript / TypeScript
- Use ES modules (import/export), not CommonJS
- Prefer `const` over `let`, never use `var`
- Use async/await over raw Promises
- Name files in kebab-case, classes in PascalCase, functions in camelCase

## Python
- Follow PEP 8
- Use type hints for function signatures
- Use pathlib over os.path
- Use f-strings over format()

## Git
- Commit messages: imperative mood, max 72 chars first line
- One logical change per commit
- Never commit secrets or API keys
