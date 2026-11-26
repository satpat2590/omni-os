# Atma

Atma is the personal growth domain included in Omni OS. Its native Mac application manages tasks and shows the World Tree. Install from the repository root and open Atma from your user Applications folder.

Task creation assigns a category and tag through the domain governance rules. Completion records points. Renaming a task keeps its identity and links. Archiving removes a task from the active list and retains its history. The World Tree reads the current tag hierarchy and completion totals from PostgreSQL.

The `api` directory contains the domain logic, database migrations and optional REST interface. The `mcp` directory contains an optional adapter for external tools. The desktop installation uses the domain logic directly over its private database socket. See [Omni's data model](../docs/DATA-MODEL.md).
