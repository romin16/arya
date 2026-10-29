# ARYA v4 migration

This is the new, clean implementation workspace. The user supplied legacy files are read-only source material and are not copied here because several contain embedded credentials. No historical Supabase memory is imported.

Target runtime: Windows 10/11, Python 3.11+, PostgreSQL with pgvector. The current execution environment has Python 3.10 and no project dependencies installed, so dependency-backed phases require setup on a supported runtime before they can be accepted.

See `docs/PHASE_1.md` and `docs/OPEN_QUESTIONS.md` for the current phase state and machine-specific prerequisites.
