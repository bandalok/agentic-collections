# Agentic Collections

A master agent crawls a content catalog and builds editorial
collections from it. Editors review each collection in a table,
approve it, or drill into its items and remove anything that
doesn't belong.

## How it works

- `agent/master_agent.py` — the master agent. Crawls the TMDB
  catalog fixture (8,643 real titles from the Synth Farm asset
  library: genres, ratings, plot summaries, streaming providers)
  and builds themed collections — Critics' Darlings, Hidden Gems,
  Based on True Stories, The Heist Crew, Space & Beyond, and more.
  Every pick carries the agent's reason ("Rated 9.1 from 1,155
  votes", "Heist plot", ...). Writes `data/collections.json`.
- `server.py` — serves the review UI and API. Editorial decisions
  (approvals, removals) persist in `data/editorial_state.json`.
  Re-running the agent never resurrects a removed item.
- `static/index.html` — the UI: collections table (name, item
  count, status, Approve button); click a count to see the items,
  each with a Remove button; removed items can be restored.

## Run

    python3 agent/master_agent.py     # build collections (once)
    python3 server.py --port 8100     # open http://localhost:8100

No dependencies beyond Python 3.10+.

## Data & licensing

Titles, artwork, and availability come from TMDB. This product uses
the TMDB API but is not endorsed or certified by TMDB. Poster
copyright belongs to the studios; demo use only.
