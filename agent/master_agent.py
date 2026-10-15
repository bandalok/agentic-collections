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

MAX_PER_COLLECTION = 150

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
            "lang": raw.get("original_language") or "",
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

# ------------------------------------------------------------------
    # Fine-grained generators: the agent mines the catalog itself.
    # ------------------------------------------------------------------

    # A. Theme mining over plot summaries.
    THEMES = [
        ("detectives", "Detective Stories", "Whodunits, procedurals, and dogged investigators.",
         ["detective", "private investigator"], 100),
        ("survival", "Fight to Survive", "Stranded, hunted, or left for dead. They endure.",
         ["survive", "survival", "stranded"], 100),
        ("music-stage", "Music & the Stage", "Bands, singers, and the price of the spotlight.",
         ["band", "musician", " singer", "rock star", "concert"], 100),
        ("high-school", "High School Years", "Lockers, first loves, and growing up in public.",
         ["high school"], 100),
        ("prison", "Behind Bars", "Prisons, inmates, and the long road out.",
         ["prison", "inmate"], 100),
        ("revenge", "Revenge Plots", "They came back for the people who wronged them.",
         ["revenge", "vengeance"], 100),
        ("magic-worlds", "Magic & Sorcery", "Wizards, witches, and spells that cut both ways.",
         ["wizard", "witch", "magic spell", " sorcerer", "sorcery"], 100),
        ("haunted", "Haunted Houses & Ghosts", "Something in this house is not at rest.",
         ["haunted", "haunting", " ghost"], 100),
        ("assassins", "Assassins & Hitmen", "Professionals. The target never sees it coming.",
         ["assassin", "hitman"], 100),
        ("kidnapped", "Kidnapped", "Taken. The clock is running.",
         ["kidnap"], 100),
        ("robots-ai", "Robots & AI", "Machines that think, feel, and sometimes rebel.",
         ["robot", "artificial intelligence", "android"], 100),
        ("mafia", "Mob & Cartel", "Families, cartels, and business conducted in whispers.",
         ["mafia", "mob boss", "cartel", "gangster"], 100),
        ("fight-game", "Fighters", "Boxers, brawlers, and one more round.",
         ["boxer", "boxing", " fighter", "martial artist"], 100),
        ("superheroes", "Superhero Stories", "Capes, powers, and impossible choices.",
         ["superhero", "super hero"], 100),
        ("spies", "Spies & Secret Agents", "Cover names, dead drops, and double crosses.",
         ["spy", "secret agent", " espionage"], 100),
        ("cult", "Cults & True Believers", "Charismatic leaders and the people who follow them anywhere.",
         [" cult"], 100),
        ("courtroom", "Courtroom Dramas", "Objection. The verdict is the twist.",
         ["courtroom", "trial of", " lawyer"], 100),
        ("thieves", "Thieves & Con Artists", "Not a heist crew. Lone wolves and long cons.",
         ["thief", "thieves", "con artist"], 100),
        ("weddings", "Weddings & Almost-Weddings", "Something borrowed, something ruined.",
         ["wedding"], 100),
        ("vampires", "Vampire Tales", "Older than the town, thirstier than ever.",
         ["vampire"], 100),
        ("christmas", "Christmas Stories", "Snow, second chances, and one perfect gift.",
         ["christmas"], 100),
        ("serial-killers", "Serial Killer Files", "Profilers, patterns, and the one who got away.",
         ["serial killer"], 100),
        ("food", "In the Kitchen", "Chefs, restaurants, and recipes worth fighting for.",
         ["chef", "cooking", "restaurant"], 100),
        ("dragons", "Here Be Dragons", "Wings, fire, and the riders who dare.",
         ["dragon"], 100),
        ("undercover", "Undercover", "Deep cover. Blown cover. No way back.",
         ["undercover"], 100),
        ("post-apocalyptic", "After the Fall", "The world ended. The story starts now.",
         ["post-apocalyptic", "apocalypse", "wasteland"], 100),
        ("zombies", "Zombie Outbreak", "Don't get bitten.",
         ["zombie"], 100),
        ("pirates", "Pirates & the High Seas", "Maps, mutinies, and buried gold.",
         ["pirate"], 100),
        ("dinosaurs", "Dinosaurs!", "Extinct is only a suggestion.",
         ["dinosaur"], 100),
        ("road-trip", "Road Trips", "Wrong turns, full tanks, no plan.",
         ["road trip"], 100),
    ]
    for tid, tname, tthesis, words, min_votes in THEMES:
        raw = [i for i in catalog
               if i["vote_count"] >= min_votes
               and any(w in i["overview_lc"] for w in words)]
        if len(raw) >= 12:
            add(f"theme-{tid}", tname, tthesis,
                f"Agent mined plot summaries for this theme; {min_votes}+ votes.",
                [pick(i, "Theme match") for i in by_popularity(raw)])

    # B. Genre-pair shelves.
    PAIRS = [
        ((18, 80), "Crime Dramas", "Gritty character dramas with a body count."),
        ((35, 18), "Dramedies", "Funny until it hurts, then funny again."),
        ((18, 9648), "Mystery Dramas", "Slow-burn dramas built around one big question."),
        ((16, 35), "Animated Comedies", "Drawn, quartered, and hilarious."),
        ((16, 12), "Animated Adventures", "Hand-drawn quests and CG epics."),
        ((878, 53), "Sci-Fi Thrillers", "The future is tense."),
        ((10749, 35), "Rom-Coms", "Meet-cute. Mess it up. Win them back."),
        ((27, 53), "Horror Thrillers", "Dread that quickens the pulse."),
        ((28, 12), "Action Adventures", "Big stunts, bigger stakes, no seatbelts."),
    ]
    for (ga, gb), pname, pthesis in PAIRS:
        raw = [i for i in catalog
               if ga in i["genre_ids"] and gb in i["genre_ids"]
               and i["vote_average"] >= 7.0 and i["vote_count"] >= 300]
        if len(raw) >= 12:
            add(f"pair-{ga}-{gb}", pname, pthesis,
                "Genre-pair shelf, rated 7.0+, 300+ votes.",
                [pick(i, "Genre pair") for i in by_rating(raw)])

    # C. Documentaries.
    docs = [i for i in catalog if 99 in i["genre_ids"]
            and i["vote_average"] >= 7.0 and i["vote_count"] >= 200]
    add("documentaries", "Documentary Deep Dives",
        "True stories, stranger than the fiction shelves.",
        "Documentary genre, rated 7.0+, 200+ votes.",
        [pick(i, "Documentary") for i in by_rating(docs)])

    # D. Decade shelves.
    for start, label in [(1980, "80s Classics"), (2000, "2000s Essentials"),
                         (2010, "2010s Defining Titles"), (2020, "The 2020s So Far")]:
        raw = [i for i in catalog if i["year"] and start <= i["year"] <= start + 9
               and i["vote_average"] >= 7.0 and i["vote_count"] >= 300]
        if len(raw) >= 12:
            add(f"decade-{start}", label,
                f"The titles that defined {start}s viewing.",
                f"Released {start}-{start + 9}, rated 7.0+, 300+ votes.",
                [pick(i, f"{i['year']} release") for i in by_popularity(raw)])

    # E. Language & region shelves.
    anime = [i for i in catalog if i.get("lang") == "ja" and 16 in i["genre_ids"]
             and i["vote_count"] >= 200]
    add("anime-essentials", "Anime Essentials",
        "The Japanese animation canon, series and films.",
        "Japanese-language animation, 200+ votes.",
        [pick(i, "Anime") for i in by_popularity(anime)])
    LANG_SHELVES = [
        ("ko", "K-Drama & Korean Hits", "Seoul stories the world binged."),
        ("es", "Spanish-Language Gems", "Dramas y comedias, sin doblaje."),
        ("hi", "Bollywood & Hindi Cinema", "Song, spectacle, and family sagas."),
        ("fr", "French Cinema & TV", "The original art-house, still at it."),
    ]
    for lang, lname, lthesis in LANG_SHELVES:
        raw = [i for i in catalog if i.get("lang") == lang and i["vote_count"] >= 100]
        if len(raw) >= 12:
            add(f"lang-{lang}", lname, lthesis,
                "Original-language shelf, 100+ votes.",
                [pick(i, "Original language pick") for i in by_popularity(raw)])

    # F. Provider shelves.
    PROVIDER_SHELVES = [
        ("Amazon Prime Video", "Prime Video Picks", "The best of the Prime catalog."),
        ("Hulu", "Best of Hulu", "Hulu's top shelf, movies and series."),
        ("Crunchyroll", "Crunchyroll Anime Shelf", "What the anime crowd is watching."),
    ]
    for prov, pname, pthesis in PROVIDER_SHELVES:
        raw = [i for i in catalog if prov in i["providers"]
               and i["vote_average"] >= 7.0 and i["vote_count"] >= 300]
        if len(raw) >= 12:
            add(f"provider-{prov.split()[0].lower()}", pname, pthesis,
                f"Streaming on {prov}, rated 7.0+, 300+ votes.",
                [pick(i, f"On {prov}") for i in by_popularity(raw)])

    # G. The most elite rating band.
    club = [i for i in catalog if i["vote_average"] >= 8.5 and i["vote_count"] >= 300]
    add("the-85-club", "The 8.5 Club",
        "The smallest, proudest room in the catalog.",
        "Rated 8.5 or higher with 300+ votes.",
        [pick(i, f"Rated {i['vote_average']:.1f}") for i in by_rating(club)])

    return [c for c in collections if len(c["items"]) >= 8]


def build_tentpoles(catalog):
    """Seasonal tentpole events, each with its own specialized collections."""
    def pick(item, why):
        return {
            "tmdb_id": item["tmdb_id"], "title": item["title"],
            "media_type": item["media_type"],
            "year": item["year"], "poster_path": item["poster_path"],
            "vote_average": item["vote_average"],
            "vote_count": item["vote_count"], "genres": item["genres"],
            "why": why,
        }

    def fin(cid, name, thesis, rule, items):
        seen, uniq = set(), []
        for it in items:
            if it["tmdb_id"] not in seen:
                seen.add(it["tmdb_id"])
                uniq.append(it)
        return {"id": cid, "name": name, "thesis": thesis, "rule": rule,
                "items": uniq[:MAX_PER_COLLECTION]}

    def by_pop(items):
        return sorted(items, key=lambda i: -i["popularity"])

    def by_rate(items):
        return sorted(items, key=lambda i: (-i["vote_average"], -i["vote_count"]))

    def kw(words, mv=100):
        return [i for i in catalog if i["vote_count"] >= mv
                and any(w in i["overview_lc"] for w in words)]

    def gen(g, mv=100):
        return [i for i in catalog if g in i["genre_ids"] and i["vote_count"] >= mv]

    T = []

    def event(eid, name, when, month, day, blurb, cols):
        cols = [c for c in cols if len(c["items"]) >= 8]
        if cols:
            T.append({"id": eid, "name": name, "when": when, "month": month,
                      "day": day, "blurb": blurb, "collections": cols})

    event("new-year", "New Year's Day", "Jan 1", 1, 1,
          "Fresh starts, second chances, and feel-good resets.",
          [fin("tp-newyear-second-chances", "Fresh Starts & Second Chances",
               "New year energy: people starting over and getting it right.",
               "Plot summaries mined for second chances and new beginnings.",
               [pick(i, "Second chance story") for i in by_rate(kw(["second chance", "new beginning", "fresh start", "start over"]))]),
           fin("tp-newyear-feelgood", "Feel-Good Favorites",
               "The comfort shelf for the first weekend of the year.",
               "Comedy-dramas rated 7.5+, sorted by popularity.",
               [pick(i, "Feel-good pick") for i in by_pop(
                   [i for i in catalog if 35 in i["genre_ids"] and 18 in i["genre_ids"]
                    and i["vote_average"] >= 7.5 and i["vote_count"] >= 300])])])

    event("super-bowl", "Super Bowl Sunday", "Early Feb", 2, 8,
          "Game day stories: the gridiron, the underdogs, the dynasties.",
          [fin("tp-superbowl-gameday", "Game Day: Sports Stories",
               "Football first, but every sport with a scoreboard is welcome.",
               "Plot summaries mined for football and sports terms, 100+ votes.",
               [pick(i, "Sports story") for i in by_pop(kw(["football", "quarterback", "baseball", "basketball", "coach"]))]),
           fin("tp-superbowl-underdogs", "Underdogs & Champions",
               "The dramatic cut of the sports shelf.",
               "Sports stories in the Drama genre, top rated.",
               [pick(i, "Sports drama") for i in by_rate(
                   [i for i in kw(["football", "quarterback", "baseball", "basketball", "coach"])
                    if 18 in i["genre_ids"]])])])

    event("valentines", "Valentine's Day", "Feb 14", 2, 14,
          "Romance shelved two ways: popular and dramatic.",
          [fin("tp-valentines-romance", "Valentine's Romance",
               "The most-loved romance titles in the catalog.",
               "Romance genre, sorted by popularity.",
               [pick(i, "Romance favorite") for i in by_pop(gen(10749))]),
           fin("tp-valentines-dramas", "Romantic Dramas",
               "Love with real stakes and better dialogue.",
               "Romance + Drama, rated 7.0+, 300+ votes.",
               [pick(i, "Romantic drama") for i in by_rate(
                   [i for i in catalog if 10749 in i["genre_ids"] and 18 in i["genre_ids"]
                    and i["vote_average"] >= 7.0 and i["vote_count"] >= 300])])])

    event("st-patricks", "St. Patrick's Day", "Mar 17", 3, 17,
          "Stories from and about Ireland.",
          [fin("tp-stpatricks-irish", "Irish Stories",
               "Dublin streets, Irish families, and emigrant tales.",
               "Plot summaries mined for Ireland and Irish life.",
               [pick(i, "Irish story") for i in by_pop(kw(["ireland", "irish", "dublin"]))])])

    event("oscars", "Oscars & Awards Season", "March", 3, 15,
          "The prestige window: what the industry celebrates.",
          [fin("tp-oscars-elite", "Awards Season Elite",
               "Only the highest-rated, most-voted titles in the building.",
               "Rated 8.5+ with 1,000+ votes.",
               [pick(i, f"Rated {i['vote_average']:.1f}") for i in by_rate(
                   [i for i in catalog if i["vote_average"] >= 8.5 and i["vote_count"] >= 1000])]),
           fin("tp-oscars-dramas", "Critics' Choice Dramas",
               "The drama shelf the critics would program.",
               "Drama genre, rated 8.0+, 1,000+ votes.",
               [pick(i, "Critics' drama") for i in by_rate(
                   [i for i in catalog if 18 in i["genre_ids"] and i["vote_average"] >= 8.0
                    and i["vote_count"] >= 1000])])])

    event("easter", "Easter", "Spring", 4, 5,
          "Faith, renewal, and family weekend viewing.",
          [fin("tp-easter-faith", "Faith & Inspiration",
               "Stories of belief, doubt, and grace.",
               "Plot summaries mined for faith themes.",
               [pick(i, "Faith story") for i in by_pop(kw(["faith", "bible", "jesus", "god"]))]),
           fin("tp-easter-family", "Easter Family Marathon",
               "Top family titles for the long weekend.",
               "Family genre, top rated, 300+ votes.",
               [pick(i, "Family favorite") for i in by_rate(
                   [i for i in gen(10751, 300) if i["vote_average"] >= 7.0])])])

    event("mothers-day", "Mother's Day", "May", 5, 10,
          "For and about moms.",
          [fin("tp-mothers-stories", "Stories of Mom",
               "Mothers at the center of the story.",
               "Plot summaries mined for mothers and moms.",
               [pick(i, "Mom at the center") for i in by_pop(kw(["mother", " mom "]))]),
           fin("tp-mothers-family", "Family Bonds",
               "The family-genre cut of the mom shelf.",
               "Family genre titles about mothers.",
               [pick(i, "Family bond story") for i in by_rate(
                   [i for i in kw(["mother", " mom "]) if 10751 in i["genre_ids"]])])])

    event("memorial-day", "Memorial Day", "Late May", 5, 25,
          "Remembrance weekend: war stories and true service.",
          [fin("tp-memorial-war", "War & Remembrance",
               "The war shelf, programmed for the holiday.",
               "War genre, sorted by popularity.",
               [pick(i, "War story") for i in by_pop(gen(10752))]),
           fin("tp-memorial-true", "True War Stories",
               "Drawn from real events and real people.",
               "War genre + true-story plot cues.",
               [pick(i, "True war story") for i in by_rate(
                   [i for i in gen(10752) if "true story" in i["overview_lc"]
                    or "based on" in i["overview_lc"]])])])

    event("fathers-day", "Father's Day", "June", 6, 21,
          "Dads: heroes, disasters, and everything between.",
          [fin("tp-fathers-stories", "Stories of Dad",
               "Fathers at the center of the story.",
               "Plot summaries mined for fathers and dads.",
               [pick(i, "Dad at the center") for i in by_pop(kw(["father", " dad "]))]),
           fin("tp-fathers-dramas", "Father & Family Dramas",
               "The dramatic cut of the dad shelf.",
               "Drama genre titles about fathers.",
               [pick(i, "Dad drama") for i in by_rate(
                   [i for i in kw(["father", " dad "]) if 18 in i["genre_ids"]])])])

    event("july-4th", "Independence Day", "Jul 4", 7, 4,
          "American stories, history, and peak summer spectacle.",
          [fin("tp-july4-american", "American Stories",
               "History-genre titles for the holiday weekend.",
               "History genre, top rated, 200+ votes.",
               [pick(i, "American history") for i in by_rate(
                   [i for i in gen(36, 200) if i["vote_average"] >= 7.0])]),
           fin("tp-july4-blockbusters", "Summer Blockbusters",
               "Action built for the loudest weekend of the year.",
               "Action genre, sorted by popularity.",
               [pick(i, "Summer blockbuster") for i in by_pop(gen(28, 300))]),
           fin("tp-july4-summer", "Beach & Summer Vibes",
               "Sun, surf, and summer trouble.",
               "Plot summaries mined for summer and beach stories.",
               [pick(i, "Summer story") for i in by_pop(kw(["summer", "beach"]))])])

    event("back-to-school", "Back to School", "September", 9, 1,
          "Hall passes, first days, and campus chaos.",
          [fin("tp-school-highschool", "Back to School: High School",
               "The high school shelf for the season.",
               "Plot summaries mined for high school stories.",
               [pick(i, "High school story") for i in by_pop(kw(["high school"]))]),
           fin("tp-school-campus", "Campus Life",
               "College towns, dorms, and degrees of trouble.",
               "Plot summaries mined for college and campus life.",
               [pick(i, "Campus story") for i in by_pop(kw(["college", "campus", "university"]))])])

    event("halloween", "Halloween", "Oct 31", 10, 31,
          "Spooky season HQ: the biggest tentpole in streaming.",
          [fin("tp-halloween-essentials", "Spooky Season Essentials",
               "The most popular horror in the catalog.",
               "Horror genre, sorted by popularity.",
               [pick(i, "Horror essential") for i in by_pop(gen(27))]),
           fin("tp-halloween-masterpieces", "Horror Masterpieces",
               "The critically feared cut.",
               "Horror genre, top rated, 300+ votes.",
               [pick(i, "Horror masterpiece") for i in by_rate(
                   [i for i in gen(27, 300) if i["vote_average"] >= 7.0])]),
           fin("tp-halloween-monsters", "Monster Mash",
               "Vampires, zombies, werewolves, ghosts, and things unnamed.",
               "Plot summaries mined for monsters and creatures.",
               [pick(i, "Monster feature") for i in by_pop(kw(["vampire", "zombie", "werewolf", "monster", "ghost"]))]),
           fin("tp-halloween-family", "Family Frights",
               "Spooky, not scarred: horror the whole family survives.",
               "Horror titles also tagged Family or Animation.",
               [pick(i, "Family fright") for i in by_pop(
                   [i for i in gen(27) if 10751 in i["genre_ids"] or 16 in i["genre_ids"]])])])

    event("thanksgiving", "Thanksgiving", "November", 11, 26,
          "Home, food, family, and football weather.",
          [fin("tp-thanks-food", "Food & the Table",
               "Chefs and kitchens for the food holiday.",
               "Plot summaries mined for cooking and restaurants.",
               [pick(i, "Food story") for i in by_pop(kw(["chef", "cooking", "restaurant"]))]),
           fin("tp-thanks-family", "Home for Thanksgiving",
               "Family titles to run all weekend.",
               "Family genre, sorted by popularity.",
               [pick(i, "Family favorite") for i in by_pop(gen(10751, 300))]),
           fin("tp-thanks-dramas", "Family Gathering Dramas",
               "Relatives, secrets, and one long table.",
               "Family + Drama, rated 7.0+, 300+ votes.",
               [pick(i, "Family drama") for i in by_rate(
                   [i for i in catalog if 10751 in i["genre_ids"] and 18 in i["genre_ids"]
                    and i["vote_average"] >= 7.0 and i["vote_count"] >= 300])])])

    event("christmas", "Christmas", "Dec 25", 12, 25,
          "The biggest shelf of the year.",
          [fin("tp-christmas-stories", "Christmas Stories",
               "Every Christmas plot in the catalog, one shelf.",
               "Plot summaries mined for Christmas; seasonal quality bar.",
               [pick(i, "Christmas story") for i in by_pop(kw(["christmas"], mv=25))]),
           fin("tp-christmas-family", "Christmas Family Marathon",
               "Family-genre holiday viewing.",
               "Family genre + Christmas plot cues.",
               [pick(i, "Christmas family pick") for i in by_rate(
                   [i for i in kw(["christmas"], mv=25) if 10751 in i["genre_ids"]])]),
           fin("tp-christmas-romance", "Holiday Romance",
               "Romance under the mistletoe.",
               "Romance genre + holiday plot cues.",
               [pick(i, "Holiday romance") for i in by_rate(
                   [i for i in kw(["christmas", "holiday", "santa", "mistletoe",
                                   "reindeer", "festive", "north pole", "winter",
                                   "snow"], mv=10)
                    if 10749 in i["genre_ids"]])])])

    return T

def main():
    catalog = load_catalog()
    collections = build_collections(catalog)
    tentpoles = build_tentpoles(catalog)
    payload = {
        "source": "TMDB catalog fixture (Synth Farm asset library)",
        "catalog_size": len(catalog),
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
        "collections": collections,
        "tentpoles": tentpoles,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1))
    total = sum(len(c["items"]) for c in collections)
    tp_total = sum(len(c["items"]) for t in tentpoles for c in t["collections"])
    print(f"Master agent crawled {len(catalog)} titles -> "
          f"{len(collections)} collections, {total} total picks; "
          f"{len(tentpoles)} tentpoles, {tp_total} seasonal picks")
    for c in collections:
        print(f"  {c['name']}: {len(c['items'])}")
    for t in tentpoles:
        names = ", ".join(f"{c['name']} ({len(c['items'])})" for c in t["collections"])
        print(f"  [TP] {t['name']}: {names}")


if __name__ == "__main__":
    main()
