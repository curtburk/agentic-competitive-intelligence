# Competitive Intelligence Pipeline - Lessons Learned

## Architecture Decisions

- **Wiki as single source of truth**: Eliminated dual storage (SQLite + wiki).
  Brief state reads from wiki/briefs/ markdown files. SQLite only for traces.
  One source of truth reduces consistency bugs.

- **Writer does prose only**: Originally asked the Writer to reproduce structured
  data (positioning comparisons, threats) that the Strategist already produced.
  Simplified to: executive summary + talking points + changes. Structured data
  flows from upstream nodes directly to the wiki.

- **Return None, not raise**: Agent failures return None rather than raising
  exceptions. Keeps pipeline control flow readable. You can read run_pipeline
  top-to-bottom and see exactly what happens when each node fails.

- **Own your vLLM instance**: Don't share inference servers between unrelated
  projects. Two projects coupled to one vLLM instance means one project's
  load/config changes break the other.
