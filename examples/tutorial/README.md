# Tutorial Examples

Runnable code that accompanies the MCP Mesh tutorials on [mcp-mesh.ai](https://mcp-mesh.ai).

Each subdirectory in `examples/tutorial/` is a multi-day, narrative-style tutorial that
builds one application across a sequence of chapters. Every day's folder is a self-contained
runnable snapshot of what the tutorial produces by the end of that chapter — so you can
clone the repo, jump to any day, and run it.

## Available tutorials

| Tutorial      | Description                                                                | Days |
| ------------- | -------------------------------------------------------------------------- | ---- |
| `trip-planner/` | Build a multi-agent travel assistant from a single tool to Kubernetes.   | 10   |

## How the examples are laid out

Each tutorial uses the same directory shape:

```
examples/tutorial/<tutorial-name>/
├── README.md              # overview, arc, how to run
├── day-01/
│   ├── README.md          # what runs, how to run it, expected output
│   ├── python/            # Python implementation
│   │   └── <agent>/
│   │       ├── main.py
│   │       └── requirements.txt
│   ├── typescript/        # TypeScript implementation (added in later waves)
│   └── java/              # Java implementation (added in later waves)
├── day-02/
├── ...
└── day-10/
```

## Why each day is a full snapshot

The tutorial is progressive — every chapter adds to what the previous one built. Keeping
each day as a standalone snapshot lets you:

- Jump straight to any day without working through the previous ones
- Compare adjacent days with `diff -r day-01 day-02` to see exactly what changed
- Re-run a past day to reproduce an earlier behavior
- Use any day as a template for your own project

The downside is duplication across days. That's intentional — it makes every chapter
directly runnable and diffable.

## Running the examples

See the `README.md` inside each tutorial's directory for tutorial-specific instructions.
The short version: `cd` into any `day-N/<language>/<agent>/` directory and follow the
steps in that day's README.

## Relationship to the website tutorial

These files are the source that the website tutorial pulls code from via
`pymdownx.snippets`. Every code block on `mcp-mesh.ai/tutorial/...` is pulled directly
from the files here, so prose and code never drift. Changing a function signature in an
example file changes it everywhere.
