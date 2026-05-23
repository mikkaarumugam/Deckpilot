"""DeckPilot HTTP backend.

Thin FastAPI wrapper around the existing `deckpilot/` Python package.
Exposes the same parsing / execution / state / undo behavior the Streamlit
dashboard uses today, but over HTTP for the React frontend.

See docs/MIGRATION.md and docs/DECISIONS.md § D-018 for context.
"""
