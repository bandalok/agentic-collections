"""Master Agent for Agentic Collections.

Crawls the local TMDB catalog fixture (8,643 real titles built for the
Synth Farm) and builds editorial collections out of it: themed shelves
derived from genres, ratings, plot keywords, eras, and streaming
providers. Every item carries a plain-English reason for why the agent
picked it, so the editorial team can judge each pick at a glance.

Data is offline and deterministic: same catalog in, same collections
out. No network calls. Run directly to (re)generate
``data/collections.json``:

    python3 agent/master_agent.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog_tmdb.json"
OUTPUT_PATH = ROOT / "data" / "collections.json"

MAX_PER_COLLECTION = 60

GENRE_NAMES = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Science Fiction",
    10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
    10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap",
    10767: "Talk", 10768: "War & Politics",
}


def load_catalog() -> list[dict]:
    data = json.loads(CATALOG_PATH.read_text())
    items = []
    for raw in data["items"]:
        overview = (raw.get("overview") or "").strip()
        date = raw.get("release_date") or raw.get("first_air_date") or ""
        year = int(date[:4]) if date[:4].isdigit() else None
        items.append({
            "tmdb_id": raw["tmdb_id"],
            "title": raw["title"],
            "media_type": raw["media_type"],
            "year": year,
            "genres": [GENRE_NAMES.get(g, "") for g in raw.get("genre_ids", [])],
            "genre_ids": raw.get("genre_ids", []),
            "overview": overview,
            "overview_lc": overview.lower(),
            "poster_path": raw.get("poster_path") or "",
            "popularity": float(raw.get("popularity") or 0),
            "vote_average": float(raw.get("vote_average") or 0),
            "vote_count": int(raw.get("vote_count") or 0),
            "providers": raw.get("providers_flatrate") or [],
        })
    return items


def pick(item: dict, why: str) -> dict:
    return {
        "tmdb_id": item["tmdb_id"],
        "title": item["title"],
        "media_type": item["media_type"],
        "year": item["year"],
        "genres": [g for g in item["genres"] if g][:3],
        "poster_path": item["poster_path"],
        "vote_average": item["vote_average"],
        "vote_count": item["vote_count"],
        "popularity": item["popularity"],
        "why": why,
    }


def by_rating(items):
    return sorted(items, key=lambda i: (-i["vote_average"], -i["vote_count"]))


def by_popularity(items):
    return sorted(items, key=lambda i: -i["popularity"])


def keyword_search(items, words, label):
    """Titles whose plot summary hits any keyword; why = matched word."""
    out = []
    for it in items:
        for w in words:
            if w in it["overview_lc"]:
                out.append(pick(it, f"Plot matches '{label}'"))
                break
    return out


def build_collections(catalog: list[dict]) -> list[dict]:
    collections = []

    def add(cid, name, thesis, rule, items):
        seen, uniq = set(), []
        for p in items:
            if p["tmdb_id"] not in seen:
                seen.add(p["tmdb_id"])
                uniq.append(p)
        collections.append({
            "id": cid, "name": name, "thesis": thesis, "rule": rule,
            "items": uniq[:MAX_PER_COLLECTION],
        })

    # 1. The best-rated titles in the whole catalog.
    elite = [i for i in catalog if i["vote_average"] >= 8.0 and i["vote_count"] >= 1000]
    add("critics-darlings", "Critics' Darlings",
        "The highest-rated titles in the catalog, full stop.",
        "Rating 8.0+ with at least 1,000 votes, sorted by rating.",
        [pick(i, f"Rated {i['vote_average']:.1f} from {i['vote_count']:,} votes")
         for i in by_rating(elite)])

    # 2. Great titles most people have never heard of.
    pop_sorted = sorted(catalog, key=lambda i: i["popularity"])
    low_pop_ids = {i["tmdb_id"] for i in pop_sorted[: len(pop_sorted) // 2]}
    gems = [i for i in catalog
            if i["vote_average"] >= 7.5 and i["vote_count"] >= 300
            and i["tmdb_id"] in low_pop_ids]
    add("hidden-gems", "Hidden Gems",
        "Highly rated, barely discovered. The agent's favorite kind of find.",
        "Rating 7.5+ and 300+ votes, but in the bottom half for popularity.",
        [pick(i, f"Rated {i['vote_average']:.1f} but flying under the radar")
         for i in by_rating(gems)])

    # 3. True stories.
    true_story = keyword_search(
        catalog,
        ["true story", "based on a true", "based on the true", "real-life",
         "real life events", "actual events", "biography of", "memoir"],
        "true story")
    true_story = [p for p in true_story if True]
    raw_ts = [i for i in catalog if any(w in i["overview_lc"] for w in
              ["true story", "based on a true", "based on the true",
               "real-life", "real life events", "actual events",
               "biography of", "memoir"]) and i["vote_count"] >= 100]
    add("true-stories", "Based on True Stories",
        "Truth, stranger and better than fiction.",
        "Plot summaries citing a true story, real events, or a memoir; 100+ votes.",
        [pick(i, "Based on real events") for i in by_rating(raw_ts)])

    # 4. Heists.
    raw_heist = [i for i in catalog
                 if any(w in i["overview_lc"] for w in
                        ["heist", "robbery", "rob a", "steal the", "bank robber",
                         "crew of thieves", "one last job"])
                 and i["vote_count"] >= 50]
    add("heist-crew", "The Heist Crew",
        "One last job. It never goes as planned.",
        "Plot keyword match on heists and robberies; 50+ votes.",
        [pick(i, "Heist plot") for i in by_popularity(raw_heist)])

    # 5. Space.
    raw_space = [i for i in catalog
                 if any(w in i["overview_lc"] for w in
                        ["spacecraft", "astronaut", "outer space", "spaceship",
                         "alien planet", "deep space", " nasa", "the galaxy"])
                 and i["vote_count"] >= 50]
    add("space-beyond", "Space & Beyond",
        "Off-world stories, from hard sci-fi to galaxy-spanning epics.",
        "Plot keyword match on space travel and alien worlds; 50+ votes.",
        [pick(i, "Set in space") for i in by_popularity(raw_space)])

    # 6. War stories (genre-driven).
    war = [i for i in catalog
           if (10752 in i["genre_ids"] or 10768 in i["genre_ids"])
           and i["vote_count"] >= 100]
    add("war-stories", "War Stories",
        "Battlefields, soldiers, and the home front.",
        "War genre titles with 100+ votes, sorted by rating.",
        [pick(i, "War genre") for i in by_rating(war)])

    # 7. 90s throwbacks.
    nineties = [i for i in catalog if i["year"] and 1990 <= i["year"] <= 1999
                and i["vote_count"] >= 500]
    add("nineties-throwbacks", "90s Throwbacks",
        "The decade that raised a generation of movie fans.",
        "Released 1990-1999 with 500+ votes, sorted by popularity.",
        [pick(i, f"{i['year']} release") for i in by_popularity(nineties)])

    # 8. Family movie night.
    family = [i for i in catalog
              if (10751 in i["genre_ids"] or 10762 in i["genre_ids"])
              and i["vote_average"] >= 6.5 and i["vote_count"] >= 200]
    add("family-night", "Family Movie Night",
        "Safe bets for the whole couch.",
        "Family/Kids genre, rated 6.5+, 200+ votes.",
        [pick(i, "Family pick") for i in by_rating(family)])

    # 9. Neo-noir: crime meets thriller/mystery.
    noir = [i for i in catalog
            if 80 in i["genre_ids"] and (53 in i["genre_ids"] or 9648 in i["genre_ids"])
            and i["vote_average"] >= 7.0 and i["vote_count"] >= 300]
    add("neo-noir", "Neo-Noir Nights",
        "Crime, shadows, and detectives who should know better.",
        "Crime + Thriller/Mystery genres, rated 7.0+, 300+ votes.",
        [pick(i, "Crime thriller") for i in by_rating(noir)])

    # 10. Prestige TV.
    prestige_tv = [i for i in catalog if i["media_type"] == "tv"
                   and i["vote_average"] >= 8.0 and i["vote_count"] >= 500]
    add("prestige-tv", "Prestige TV",
        "The series people write essays about.",
        "TV only, rated 8.0+, 500+ votes.",
        [pick(i, f"Rated {i['vote_average']:.1f}") for i in by_rating(prestige_tv)])

    # 11. Horror after dark.
    horror = [i for i in catalog if 27 in i["genre_ids"]
              and i["vote_average"] >= 6.5 and i["vote_count"] >= 200]
    add("horror-after-dark", "Horror After Dark",
        "Watch with the lights on. Or don't.",
        "Horror genre, rated 6.5+, 200+ votes.",
        [pick(i, "Horror pick") for i in by_rating(horror)])

    # 12. Love stories.
    romance = [i for i in catalog if 10749 in i["genre_ids"]
               and i["vote_average"] >= 7.0 and i["vote_count"] >= 300]
    add("love-stories", "Love Stories",
        "Meet-cutes, heartbreaks, and second chances.",
        "Romance genre, rated 7.0+, 300+ votes.",
        [pick(i, "Romance pick") for i in by_rating(romance)])

    # 13. Mind-benders.
    raw_mind = [i for i in catalog
                if any(w in i["overview_lc"] for w in
                       ["time travel", "time-travel", "parallel universe",
                        "simulation", "memory loss", "recurring dream",
                        "time loop", "alternate reality"])
                and i["vote_count"] >= 100]
    add("mind-benders", "Mind-Benders",
        "Time loops, false memories, and realities that fold.",
        "Plot keyword match on time travel, loops, and alternate realities; 100+ votes.",
        [pick(i, "Reality-bending plot") for i in by_popularity(raw_mind)])

    # 14. Free to watch right now (ad-supported streamers).
    free = [i for i in catalog
            if any(p in i["providers"] for p in
                   ("Tubi TV", "The Roku Channel", "Pluto TV", "Freevee"))
            and i["vote_average"] >= 6.8 and i["vote_count"] >= 300]
    add("free-to-watch", "Free to Watch Tonight",
        "Zero subscription required. All killer, no bill.",
        "Streaming free on Tubi / Roku Channel / Pluto / Freevee, rated 6.8+, 300+ votes.",
        [pick(i, "Free to stream") for i in by_rating(free)])

    # 15. Netflix top shelf.
    netflix = [i for i in catalog
               if "Netflix" in i["providers"] and i["vote_count"] >= 300]
    add("netflix-top-shelf", "Netflix Top Shelf",
        "The strongest titles Netflix US is carrying right now.",
        "Available on Netflix US, 300+ votes, sorted by popularity.",
        [pick(i, "On Netflix") for i in by_popularity(netflix)])

    return [c for c in collections if len(c["items"]) >= 8]


def main():
    catalog = load_catalog()
    collections = build_collections(catalog)
    payload = {
        "source": "TMDB catalog fixture (Synth Farm asset library)",
        "catalog_size": len(catalog),
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
        "collections": collections,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1))
    total = sum(len(c["items"]) for c in collections)
    print(f"Master agent crawled {len(catalog)} titles -> "
          f"{len(collections)} collections, {total} total picks")
    for c in collections:
        print(f"  {c['name']}: {len(c['items'])}")


if __name__ == "__main__":
    main()
