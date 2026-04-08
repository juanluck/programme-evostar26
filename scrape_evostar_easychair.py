#!/usr/bin/env python3
"""Build a friendlier EvoStar 2026 programme site from the public EasyChair page.

Default source:
    https://easychair.org/smart-program/evostar2026/index.html

Outputs:
    site/index.html
    site/program.json
    site/program_snapshot.txt

The generated site is static and ready for GitHub Pages.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

DEFAULT_URL = "https://easychair.org/smart-program/evostar2026/index.html"
USER_AGENT = "Mozilla/5.0 (compatible; EvoStar26ProgrammeBot/2.0; +https://www.evostar.org/)"

DAY_LINE_RE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), [A-Za-z]+ \d{1,2}(?:st|nd|rd|th)$"
)
SESSION_LINE_RE = re.compile(r"^(?P<start>\d{2}:\d{2})-(?P<end>\d{2}:\d{2}) (?P<title>.+)$")
TALK_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
PERSON_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://easychair\.org/smart-program/[^)]+/person\d+\.html)\)")
ROOM_LINK_RE = re.compile(r"Location:\s*\[([^\]]+)\]\((https://easychair\.org/smart-program/[^)]+/room\d+\.html)\)")
ABSTRACT_RE = re.compile(r"\(\[abstract\]\((https://easychair\.org/smart-program/[^)]+/\d{4}-\d{2}-\d{2}\.html#talk:\d+)\)\)")


BLOCKISH_TAGS = {
    "html", "body", "main", "section", "article", "aside", "header", "footer", "nav",
    "div", "p", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "ul", "ol",
    "li", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "br"
}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def markdown_links_to_text(text: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
        timeout=45,
    )
    response.raise_for_status()
    return response.text


def flatten_html_to_structured_text(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style", "noscript"]):
        bad.decompose()

    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, NavigableString):
            text = normalize_space(str(node))
            if text:
                parts.append(text)
            return
        if not isinstance(node, Tag):
            return
        if node.name in BLOCKISH_TAGS:
            parts.append("\n")
        if node.name == "a":
            label = normalize_space(node.get_text(" ", strip=True))
            href = node.get("href", "").strip()
            if label:
                parts.append(f"[{label}]({urljoin(base_url, href)})" if href else label)
        else:
            for child in node.children:
                walk(child)
        if node.name in BLOCKISH_TAGS:
            parts.append("\n")

    root = soup.body or soup
    walk(root)
    text = " ".join(parts)
    text = re.sub(r"[ 	]*\n[ 	]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_structured_from_snapshot(snapshot_text: str) -> str:
    for marker in ("Structured Content:", "Markdown Content:"):
        if marker in snapshot_text:
            return snapshot_text.split(marker, 1)[1].strip()
    return snapshot_text.strip()


def theme_from_name(name: str) -> str:
    if name.startswith("Plenary invited talk"):
        return "Plenary"
    if name.startswith("Conference "):
        return "Ceremony"
    if name.startswith("Poster session"):
        return "Social"
    if name.startswith("SPECIES"):
        return "Meeting"
    if name.startswith("Optional"):
        return "Social"
    if name in {
        "Lunch", "Coffee break", "Break", "Conference dinner",
        "Go to pick up point", "Transport to Rochemontès"
    }:
        return "Logistics"
    match = re.match(r"(EvoMusArt|EvoMUSART|EvoApplications|EML|EuroGP|EvoCOP|Evo\*)\b", name)
    if match:
        return match.group(1).replace("EvoMUSART", "EvoMusArt")
    return "Other"


def parse_person_names(text: str) -> list[str]:
    names = [m.group(1) for m in PERSON_LINK_RE.finditer(text)]
    if names:
        return names
    plain = markdown_links_to_text(text)
    if not plain:
        return []
    return [chunk.strip() for chunk in re.split(r",| and ", plain) if chunk.strip()]


def parse_room(line: str) -> tuple[str | None, str | None]:
    match = ROOM_LINK_RE.search(line)
    if match:
        return match.group(1), match.group(2)
    plain = re.match(r"Location:\s*(.+)$", markdown_links_to_text(line))
    if plain:
        return plain.group(1).strip(), None
    return None, None


def looks_like_author_line(line: str) -> bool:
    if not line or line.startswith("PRESENTER:") or line.startswith("ABSTRACT."):
        return False
    if PERSON_LINK_RE.search(line):
        return True

    plain = markdown_links_to_text(line)
    if len(plain) > 220 or ":" in plain or "?" in plain:
        return False

    tokens = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’.-]*", plain)
    if not tokens:
        return False

    lowercase_exceptions = {"and", "de", "del", "da", "dos", "van", "von", "la", "le", "di", "du", "jr", "ii", "iii"}
    lower_tokens = [t for t in tokens if t.islower() and t.lower() not in lowercase_exceptions]
    if lower_tokens:
        return False

    punct = {",", " and ", " & ", ";"}
    if any(mark in plain for mark in punct):
        return True

    titlecaseish = sum(1 for t in tokens if t[:1].isupper())
    return titlecaseish == len(tokens) and len(tokens) <= 12


def parse_presenter(line: str) -> str | None:
    if not line.startswith("PRESENTER:"):
        return None
    linked = re.search(r"PRESENTER:\s*\[([^\]]+)\]\(", line)
    if linked:
        return linked.group(1)
    plain = markdown_links_to_text(line.split(":", 1)[1]).strip()
    return plain or None


def parse_talk_block(lines: list[str], session: dict[str, Any], day_label: str) -> dict[str, Any] | None:
    if not lines:
        return None

    talk_start = lines[0]
    body = [line for line in lines[1:] if line]
    if not body:
        return None

    joined = normalize_space(" ".join(body))
    abstract_match = ABSTRACT_RE.search(joined)
    abstract_url = abstract_match.group(1) if abstract_match else None

    presenter = next((parse_presenter(line) for line in body if line.startswith("PRESENTER:")), None)

    abstract_idx = next((i for i, line in enumerate(body) if line.startswith("ABSTRACT.")), None)
    presenter_idx = next((i for i, line in enumerate(body) if line.startswith("PRESENTER:")), None)
    cutoff_candidates = [idx for idx in (presenter_idx, abstract_idx) if idx is not None]
    content_cutoff = min(cutoff_candidates) if cutoff_candidates else len(body)
    preamble = body[:content_cutoff]

    authors: list[str] = []
    title_lines: list[str] = []

    if abstract_match:
        before_abstract = normalize_space(joined[:abstract_match.start()])
        author_matches = list(PERSON_LINK_RE.finditer(before_abstract))
        authors = [match.group(1) for match in author_matches]
        title_source = before_abstract[author_matches[-1].end():] if author_matches else before_abstract
        title = normalize_space(markdown_links_to_text(title_source))
        title = re.sub(r"^(?:,|and)\s*", "", title)
        if title:
            title_lines = [title]

    if not title_lines:
        idx = 0
        while idx < len(preamble) and looks_like_author_line(preamble[idx]):
            authors.extend(parse_person_names(preamble[idx]))
            idx += 1

        title_lines = [markdown_links_to_text(line) for line in preamble[idx:] if not looks_like_author_line(line)]
        if not title_lines and preamble:
            title_lines = [markdown_links_to_text(preamble[-1])]
            if len(preamble) > 1:
                for line in preamble[:-1]:
                    authors.extend(parse_person_names(line))

    title = normalize_space(" ".join(title_lines))
    title = re.sub(r"\s*\(\s*abstract\s*\)\s*", "", title, flags=re.IGNORECASE)
    title = normalize_space(title)

    if not title:
        return None

    cleaned_authors: list[str] = []
    for author in authors:
        author = normalize_space(markdown_links_to_text(author))
        if author and author not in cleaned_authors:
            cleaned_authors.append(author)

    return {
        "day": day_label,
        "start": talk_start,
        "end": session["end"],
        "title": title,
        "authors": cleaned_authors,
        "presenter": presenter,
        "abstract_url": abstract_url,
        "room": session["room"],
        "session_code": session["session_code"],
        "session_name": session["session_name"],
        "session_title": session["title"],
        "theme": session["theme"],
    }


def parse_program(structured_text: str, source_url: str) -> dict[str, Any]:
    raw_lines = [normalize_space(line) for line in structured_text.splitlines()]
    lines = [line for line in raw_lines if line]
    day_indices = [i for i, line in enumerate(lines) if DAY_LINE_RE.match(line)]
    if not day_indices:
        raise ValueError("Could not detect programme days. EasyChair may have changed its format.")

    program: dict[str, Any] = {
        "conference": "EvoStar 2026",
        "source_url": source_url,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "days": [],
    }

    for day_pos, day_start in enumerate(day_indices):
        day_end = day_indices[day_pos + 1] if day_pos + 1 < len(day_indices) else len(lines)
        day_label = lines[day_start]
        day_lines = lines[day_start + 1:day_end]
        day_obj: dict[str, Any] = {"label": day_label, "sessions": []}
        i = 0
        while i < len(day_lines):
            line = day_lines[i]
            if line.startswith("View this program:"):
                i += 1
                continue
            session_match = SESSION_LINE_RE.match(line)
            if not session_match:
                i += 1
                continue

            session_title = session_match.group("title")
            session: dict[str, Any] = {
                "day": day_label,
                "start": session_match.group("start"),
                "end": session_match.group("end"),
                "title": session_title,
                "chairs": [],
                "room": None,
                "room_url": None,
                "talks": [],
                "notes": None,
            }
            named_match = re.match(r"Session\s+([^\s:]+):\s*(.*)", session_title)
            if named_match:
                session["session_code"] = named_match.group(1)
                session["session_name"] = named_match.group(2)
            else:
                session["session_code"] = None
                session["session_name"] = session_title
            session["theme"] = theme_from_name(session["session_name"])

            i += 1
            notes: list[str] = []

            if i < len(day_lines) and re.match(r"^Chair[s]?:$", day_lines[i]):
                i += 1
                chair_lines: list[str] = []
                while i < len(day_lines):
                    probe = day_lines[i]
                    if probe.startswith("Location:") or SESSION_LINE_RE.match(probe) or TALK_TIME_RE.match(probe) or DAY_LINE_RE.match(probe):
                        break
                    chair_lines.append(probe)
                    i += 1
                chair_text = normalize_space(" ".join(chair_lines))
                session["chairs"] = parse_person_names(chair_text)

            if i < len(day_lines) and day_lines[i].startswith("Location:"):
                room, room_url = parse_room(day_lines[i])
                session["room"] = room
                session["room_url"] = room_url
                i += 1

            while i < len(day_lines):
                probe = day_lines[i]
                if SESSION_LINE_RE.match(probe) or DAY_LINE_RE.match(probe):
                    break
                if TALK_TIME_RE.match(probe):
                    talk_lines = [probe]
                    i += 1
                    while i < len(day_lines):
                        lookahead = day_lines[i]
                        if SESSION_LINE_RE.match(lookahead) or DAY_LINE_RE.match(lookahead) or TALK_TIME_RE.match(lookahead):
                            break
                        talk_lines.append(lookahead)
                        i += 1
                    talk = parse_talk_block(talk_lines, session, day_label)
                    if talk:
                        session["talks"].append(talk)
                    continue
                if probe != "Chair:" and probe != "Chairs:" and not probe.startswith("Location:"):
                    notes.append(probe)
                i += 1

            note_text = normalize_space(markdown_links_to_text(" ".join(notes)))
            session["notes"] = note_text or None
            for talk_index, talk in enumerate(session["talks"]):
                talk["end"] = session["talks"][talk_index + 1]["start"] if talk_index + 1 < len(session["talks"]) else session["end"]
            day_obj["sessions"].append(session)

        program["days"].append(day_obj)

    program["stats"] = {
        "days": len(program["days"]),
        "sessions": sum(len(day["sessions"]) for day in program["days"]),
        "talks": sum(len(session["talks"]) for day in program["days"] for session in day["sessions"]),
        "rooms": len({session["room"] for day in program["days"] for session in day["sessions"] if session["room"]}),
    }
    return program

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EvoStar 2026 - Friendly programme</title>
  <meta name="description" content="Friendly EvoStar 2026 programme view built from the public EasyChair schedule." />
  <style>
    :root {
      --bg: #f6f9fd;
      --bg-2: #edf4fb;
      --paper: #ffffff;
      --paper-soft: #f7fbff;
      --text: #122033;
      --muted: #5f6f86;
      --line: rgba(18, 32, 51, .12);
      --blue: #0046a5;
      --cyan: #4696a0;
      --orange: #eb6e32;
      --amber: #ffaa32;
      --red: #a02828;
      --shadow: 0 20px 60px rgba(15, 31, 53, .10);
      --radius: 20px;
    }

    * { box-sizing: border-box; }

    html, body {
      margin: 0;
      padding: 0;
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 8% 0%, rgba(70, 150, 160, .16), transparent 28%),
        radial-gradient(circle at 92% 4%, rgba(235, 110, 50, .14), transparent 24%),
        linear-gradient(180deg, var(--bg-2) 0%, #f9fbfe 42%, #ffffff 100%);
    }

    a {
      color: var(--blue);
      text-decoration: none;
    }

    a:hover {
      text-decoration: underline;
    }

    .wrap {
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px 20px 56px;
    }

    .hero {
      position: relative;
      overflow: hidden;
      border-radius: 32px;
      padding: 32px;
      background:
        linear-gradient(135deg, rgba(255,255,255,.96), rgba(255,255,255,.88)),
        linear-gradient(180deg, rgba(255,255,255,.96), rgba(255,255,255,.96));
      border: 1px solid rgba(255,255,255,.75);
      box-shadow: var(--shadow);
    }

    .hero::before,
    .hero::after {
      content: "";
      position: absolute;
      border-radius: 999px;
      filter: blur(10px);
      pointer-events: none;
    }

    .hero::before {
      width: 340px;
      height: 340px;
      right: -110px;
      top: -120px;
      background: radial-gradient(circle, rgba(255,170,50,.28) 0%, rgba(235,110,50,.18) 40%, rgba(235,110,50,0) 72%);
    }

    .hero::after {
      width: 320px;
      height: 320px;
      left: -120px;
      bottom: -150px;
      background: radial-gradient(circle, rgba(70,150,160,.22) 0%, rgba(0,70,165,.10) 46%, rgba(70,150,160,0) 76%);
    }

    .hero-top {
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(260px, .8fr);
      gap: 24px;
      align-items: center;
    }

    .eyebrow-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 14px;
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(18, 32, 51, .08);
      background: rgba(255,255,255,.7);
      color: var(--muted);
      font-size: .92rem;
      font-weight: 700;
    }

    .eyebrow strong {
      color: var(--text);
    }

    h1 {
      margin: 0;
      font-size: clamp(2rem, 4vw, 3.5rem);
      line-height: 1.02;
      letter-spacing: -.04em;
      max-width: 12ch;
    }

    .subtitle {
      margin: 14px 0 0;
      max-width: 64ch;
      color: var(--muted);
      font-size: 1.03rem;
      line-height: 1.65;
    }

    .hero-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }

    .brand-link {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid rgba(0,70,165,.14);
      background: rgba(0,70,165,.06);
      color: var(--blue);
      font-weight: 700;
    }

    .brand-link.alt {
      border-color: rgba(235,110,50,.15);
      background: rgba(255,170,50,.12);
      color: #9f4c08;
    }

    .hero-brand {
      display: grid;
      gap: 14px;
      justify-items: stretch;
    }

    .logo-card {
      border-radius: 24px;
      background:
        radial-gradient(circle at top left, rgba(255,170,50,.12), transparent 34%),
        linear-gradient(145deg, #0d1624, #18263a);
      border: 1px solid rgba(255,255,255,.08);
      padding: 18px 20px;
      box-shadow: 0 18px 45px rgba(8, 18, 35, .25);
    }

    .hero-logo {
      display: block;
      width: 100%;
      height: auto;
    }

    .stats {
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 14px;
      margin-top: 22px;
    }

    .stat {
      border-radius: 20px;
      background: rgba(255,255,255,.74);
      border: 1px solid rgba(18, 32, 51, .08);
      padding: 16px 18px;
      box-shadow: 0 8px 24px rgba(15, 31, 53, .06);
    }

    .stat .n {
      font-size: 1.6rem;
      font-weight: 800;
      letter-spacing: -.03em;
    }

    .stat .k {
      margin-top: 4px;
      color: var(--muted);
      font-size: .94rem;
    }

    .toolbar {
      position: sticky;
      top: 12px;
      z-index: 20;
      margin: 18px 0 22px;
      padding: 14px;
      border-radius: 24px;
      border: 1px solid rgba(18, 32, 51, .08);
      background: rgba(255,255,255,.82);
      box-shadow: 0 16px 40px rgba(15, 31, 53, .08);
      backdrop-filter: blur(16px);
    }

    .toolbar-grid {
      display: grid;
      grid-template-columns: 1.35fr repeat(3, minmax(150px, .65fr)) auto;
      gap: 10px;
    }

    .toolbar input,
    .toolbar select,
    .toolbar button {
      width: 100%;
      border-radius: 16px;
      border: 1px solid rgba(18, 32, 51, .1);
      background: rgba(255,255,255,.92);
      color: var(--text);
      padding: 12px 14px;
      font: inherit;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.7);
    }

    .toolbar button {
      cursor: pointer;
      font-weight: 800;
      color: white;
      border-color: transparent;
      background: linear-gradient(135deg, var(--blue), #0b5fd1);
      box-shadow: 0 12px 24px rgba(0, 70, 165, .18);
    }

    .days {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }

    .day-pill {
      border: 1px solid rgba(18, 32, 51, .08);
      background: rgba(255,255,255,.9);
      color: var(--text);
      border-radius: 999px;
      padding: 10px 14px;
      cursor: pointer;
      font-weight: 700;
    }

    .day-pill.active {
      background: linear-gradient(135deg, rgba(0,70,165,.12), rgba(70,150,160,.12));
      border-color: rgba(0,70,165,.22);
      color: var(--blue);
    }

    .schedule {
      display: grid;
      gap: 16px;
    }

    .session {
      border: 1px solid rgba(18, 32, 51, .08);
      background: linear-gradient(180deg, rgba(255,255,255,.92), rgba(248,251,255,.96));
      border-radius: 26px;
      box-shadow: 0 18px 44px rgba(15, 31, 53, .08);
      overflow: hidden;
    }

    .session-head {
      display: grid;
      grid-template-columns: 136px 1fr;
      gap: 18px;
      padding: 18px;
      align-items: start;
    }

    .timebox {
      border-radius: 18px;
      padding: 14px 12px;
      text-align: center;
      border: 1px solid rgba(18, 32, 51, .08);
      background: var(--session-soft, rgba(0,70,165,.08));
      box-shadow: inset 0 1px 0 rgba(255,255,255,.7);
    }

    .timebox .range {
      font-weight: 900;
      font-size: 1.05rem;
      letter-spacing: -.02em;
      color: var(--session-accent, var(--blue));
    }

    .timebox .room {
      margin-top: 8px;
      color: var(--muted);
      font-size: .92rem;
    }

    .session-title {
      margin: 0 0 8px;
      font-size: 1.28rem;
      letter-spacing: -.03em;
      line-height: 1.25;
    }

    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border-radius: 999px;
      border: 1px solid rgba(18, 32, 51, .08);
      background: rgba(255,255,255,.9);
      color: var(--text);
      font-size: .88rem;
      white-space: nowrap;
    }

    .chairs {
      margin-top: 4px;
      color: var(--muted);
      font-size: .98rem;
      line-height: 1.55;
    }

    .chairs strong {
      color: var(--text);
    }

    .note {
      margin-top: 8px;
      color: var(--muted);
      line-height: 1.55;
      font-size: .96rem;
    }

    .talks {
      border-top: 1px solid rgba(18, 32, 51, .08);
      background: linear-gradient(180deg, rgba(243,247,253,.85), rgba(248,251,255,.98));
      padding: 12px 18px 18px;
      display: grid;
      gap: 10px;
    }

    .talk {
      border: 1px solid rgba(18, 32, 51, .08);
      background: white;
      border-radius: 18px;
      padding: 14px 16px;
      display: grid;
      grid-template-columns: 88px 1fr;
      gap: 12px;
      box-shadow: 0 10px 26px rgba(15, 31, 53, .05);
    }

    .talk-time {
      font-weight: 900;
      color: var(--session-accent, var(--blue));
      white-space: nowrap;
      font-size: 1.02rem;
    }

    .talk-title {
      margin: 0 0 6px;
      font-size: 1.02rem;
      line-height: 1.35;
      letter-spacing: -.01em;
    }

    .talk-authors {
      color: var(--muted);
      font-size: .96rem;
      line-height: 1.45;
    }

    .talk-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
      font-size: .93rem;
    }

    .abstract-link {
      font-weight: 700;
    }

    .presenter {
      background: var(--session-soft, rgba(0,70,165,.08));
    }

    .hidden { display: none !important; }

    .empty {
      padding: 26px;
      text-align: center;
      color: var(--muted);
      border: 1px dashed rgba(18, 32, 51, .16);
      border-radius: 22px;
      background: rgba(255,255,255,.72);
    }

    .footer {
      color: var(--muted);
      margin-top: 18px;
      text-align: center;
      font-size: .92rem;
      line-height: 1.6;
    }

    @media (max-width: 1024px) {
      .hero-top,
      .toolbar-grid { grid-template-columns: 1fr 1fr; }
      .stats { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
    }

    @media (max-width: 720px) {
      .hero-top,
      .toolbar-grid { grid-template-columns: 1fr; }
      .wrap { padding-inline: 14px; }
      .hero { padding: 22px; }
      .session-head,
      .talk { grid-template-columns: 1fr; }
      .stats { grid-template-columns: 1fr 1fr; }
      h1 { max-width: none; }
    }

    @media (max-width: 520px) {
      .stats { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="hero-top">
        <div>
          <div class="eyebrow-row">
            <span class="eyebrow"><strong>EvoStar 2026</strong></span>
            <span class="eyebrow">Toulouse · 8–10 April 2026</span>
          </div>
          <h1>EvoStar 2026 - Friendly programme</h1>
          <p class="subtitle">
            A calmer, brand-aligned view of the public EasyChair schedule, with search,
            filters, and clearer navigation across sessions and talks.
          </p>
          <div class="hero-links">
            <a class="brand-link" href="__SOURCE_URL__" target="_blank" rel="noopener">EasyChair source</a>
            <a class="brand-link alt" href="https://www.evostar.org/2026/" target="_blank" rel="noopener">Conference website</a>
          </div>
        </div>
        <div class="hero-brand">
          <div class="logo-card">
            <img class="hero-logo" src="assets/evo_logo.png" alt="EvoStar logo" />
          </div>
        </div>
      </div>
      <div class="stats">
        <div class="stat"><div class="n">__STAT_DAYS__</div><div class="k">days</div></div>
        <div class="stat"><div class="n">__STAT_SESSIONS__</div><div class="k">sessions / events</div></div>
        <div class="stat"><div class="n">__STAT_TALKS__</div><div class="k">talks</div></div>
        <div class="stat"><div class="n">__STAT_ROOMS__</div><div class="k">rooms</div></div>
      </div>
    </section>

    <section class="toolbar">
      <div class="toolbar-grid">
        <input id="search" type="search" placeholder="Search session, talk, author, presenter, or chair" />
        <select id="roomFilter"><option value="">All rooms</option></select>
        <select id="themeFilter"><option value="">All themes</option></select>
        <select id="viewMode">
          <option value="expanded">Show sessions and talks</option>
          <option value="compact">Compact sessions</option>
        </select>
        <button id="resetBtn" type="button">Reset filters</button>
      </div>
      <div class="days" id="dayTabs"></div>
    </section>

    <section id="schedule" class="schedule"></section>
    <div id="emptyState" class="empty hidden">No sessions match the current filters.</div>

    <div class="footer">
      Automatically generated from the public EasyChair programme.<br />
      Last generated: __GENERATED_AT__
    </div>
  </div>

  <script>
    const PROGRAM = __PROGRAM_JSON__;

    const state = {
      day: PROGRAM.days[0]?.label || "",
      search: "",
      room: "",
      theme: "",
      view: "expanded",
    };

    const scheduleEl = document.getElementById("schedule");
    const emptyEl = document.getElementById("emptyState");
    const dayTabsEl = document.getElementById("dayTabs");
    const roomFilterEl = document.getElementById("roomFilter");
    const themeFilterEl = document.getElementById("themeFilter");
    const searchEl = document.getElementById("search");
    const viewModeEl = document.getElementById("viewMode");
    const resetBtnEl = document.getElementById("resetBtn");

    function uniq(values) {
      return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
    }

    function themeStyle(theme) {
      const styles = {
        "EuroGP": { accent: "#0046a5", soft: "rgba(0,70,165,.08)" },
        "EvoApplications": { accent: "#4696a0", soft: "rgba(70,150,160,.10)" },
        "EvoCOP": { accent: "#ffaa32", soft: "rgba(255,170,50,.16)" },
        "EvoMusArt": { accent: "#a02828", soft: "rgba(160,40,40,.10)" },
        "EML": { accent: "#4696a0", soft: "rgba(70,150,160,.10)" },
        "Plenary": { accent: "#eb6e32", soft: "rgba(235,110,50,.11)" },
        "Ceremony": { accent: "#a02828", soft: "rgba(160,40,40,.10)" },
        "Meeting": { accent: "#0046a5", soft: "rgba(0,70,165,.08)" },
        "Social": { accent: "#eb6e32", soft: "rgba(235,110,50,.11)" },
        "Logistics": { accent: "#5f6f86", soft: "rgba(95,111,134,.10)" }
      };
      return styles[theme] || { accent: "#0046a5", soft: "rgba(0,70,165,.08)" };
    }

    function populateFilters() {
      const rooms = uniq(PROGRAM.days.flatMap(day => day.sessions.map(s => s.room)));
      const themes = uniq(PROGRAM.days.flatMap(day => day.sessions.map(s => s.theme)));

      rooms.forEach(room => {
        const opt = document.createElement("option");
        opt.value = room;
        opt.textContent = room;
        roomFilterEl.appendChild(opt);
      });

      themes.forEach(theme => {
        const opt = document.createElement("option");
        opt.value = theme;
        opt.textContent = theme;
        themeFilterEl.appendChild(opt);
      });
    }

    function renderDayTabs() {
      dayTabsEl.innerHTML = "";
      PROGRAM.days.forEach(day => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "day-pill" + (state.day === day.label ? " active" : "");
        btn.textContent = day.label;
        btn.addEventListener("click", () => {
          state.day = day.label;
          renderDayTabs();
          renderSchedule();
        });
        dayTabsEl.appendChild(btn);
      });
    }

    function escapeHtml(text) {
      return String(text ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function linkify(text) {
      if (!text) return "";
      return escapeHtml(text).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    }

    function sessionSearchBlob(session) {
      const talkText = session.talks.flatMap(t => [t.title, t.presenter, ...(t.authors || [])]).join(" ");
      return [
        session.title,
        session.session_name,
        session.theme,
        session.room,
        ...(session.chairs || []),
        session.notes || "",
        talkText
      ].join(" ").toLowerCase();
    }

    function matchesFilters(session) {
      if (state.room && session.room !== state.room) return false;
      if (state.theme && session.theme !== state.theme) return false;
      if (state.search) {
        const blob = sessionSearchBlob(session);
        if (!blob.includes(state.search.toLowerCase())) return false;
      }
      return true;
    }

    function renderTalk(talk, style) {
      const presenter = talk.presenter ? `<span class="badge presenter">Presenter: ${escapeHtml(talk.presenter)}</span>` : "";
      const abstract = talk.abstract_url ? `<a class="abstract-link" href="${talk.abstract_url}" target="_blank" rel="noopener">View abstract</a>` : "";
      return `
        <article class="talk" style="--session-accent:${style.accent}; --session-soft:${style.soft};">
          <div class="talk-time">${escapeHtml(talk.start)}–${escapeHtml(talk.end)}</div>
          <div>
            <h4 class="talk-title">${escapeHtml(talk.title)}</h4>
            <div class="talk-authors">${escapeHtml((talk.authors || []).join(", "))}</div>
            <div class="talk-links">
              ${presenter}
              ${abstract}
            </div>
          </div>
        </article>
      `;
    }

    function renderSession(session) {
      const style = themeStyle(session.theme);
      const chairLabel = (session.chairs?.length || 0) > 1 ? "Chairs" : "Chair";
      const chairs = session.chairs?.length
        ? `<div class="chairs"><strong>${chairLabel}:</strong> ${escapeHtml(session.chairs.join(", "))}</div>`
        : "";

      const roomBadge = session.room ? `<span class="badge">📍 ${escapeHtml(session.room)}</span>` : "";
      const themeBadge = session.theme ? `<span class="badge">${escapeHtml(session.theme)}</span>` : "";
      const codeBadge = session.session_code ? `<span class="badge">Session ${escapeHtml(session.session_code)}</span>` : "";
      const note = session.notes ? `<div class="note">${linkify(session.notes)}</div>` : "";
      const talksHtml = session.talks.length && state.view === "expanded"
        ? `<div class="talks">${session.talks.map(talk => renderTalk(talk, style)).join("")}</div>`
        : "";

      return `
        <article class="session" style="--session-accent:${style.accent}; --session-soft:${style.soft};">
          <div class="session-head">
            <div class="timebox">
              <div class="range">${escapeHtml(session.start)}–${escapeHtml(session.end)}</div>
              <div class="room">${escapeHtml(session.room || "No room")}</div>
            </div>
            <div>
              <h3 class="session-title">${escapeHtml(session.session_name || session.title)}</h3>
              <div class="meta">${codeBadge} ${themeBadge} ${roomBadge}</div>
              ${chairs}
              ${note}
            </div>
          </div>
          ${talksHtml}
        </article>
      `;
    }

    function renderSchedule() {
      const day = PROGRAM.days.find(d => d.label === state.day) || PROGRAM.days[0];
      const sessions = day.sessions.filter(matchesFilters);

      if (!sessions.length) {
        scheduleEl.innerHTML = "";
        emptyEl.classList.remove("hidden");
        return;
      }

      emptyEl.classList.add("hidden");
      scheduleEl.innerHTML = sessions.map(renderSession).join("");
    }

    searchEl.addEventListener("input", e => {
      state.search = e.target.value.trim();
      renderSchedule();
    });
    roomFilterEl.addEventListener("change", e => {
      state.room = e.target.value;
      renderSchedule();
    });
    themeFilterEl.addEventListener("change", e => {
      state.theme = e.target.value;
      renderSchedule();
    });
    viewModeEl.addEventListener("change", e => {
      state.view = e.target.value;
      renderSchedule();
    });
    resetBtnEl.addEventListener("click", () => {
      state.search = "";
      state.room = "";
      state.theme = "";
      state.view = "expanded";
      state.day = PROGRAM.days[0]?.label || "";
      searchEl.value = "";
      roomFilterEl.value = "";
      themeFilterEl.value = "";
      viewModeEl.value = "expanded";
      renderDayTabs();
      renderSchedule();
    });

    populateFilters();
    renderDayTabs();
    renderSchedule();
  </script>
</body>
</html>
'''


def render_html(program: dict[str, Any]) -> str:
    generated_at = program.get("generated_at_utc", "").replace("T", " ").replace("+00:00", " UTC")
    html = HTML_TEMPLATE
    html = html.replace("__SOURCE_URL__", escape(program["source_url"]))
    html = html.replace("__STAT_DAYS__", str(program["stats"]["days"]))
    html = html.replace("__STAT_SESSIONS__", str(program["stats"]["sessions"]))
    html = html.replace("__STAT_TALKS__", str(program["stats"]["talks"]))
    html = html.replace("__STAT_ROOMS__", str(program["stats"]["rooms"]))
    html = html.replace("__GENERATED_AT__", escape(generated_at))
    html = html.replace("__PROGRAM_JSON__", json.dumps(program, ensure_ascii=False))
    return html


def build_site(program: dict[str, Any], snapshot_text: str, output_dir: Path, logo_source: Path | None) -> None:
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    (output_dir / "program.json").write_text(json.dumps(program, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "program_snapshot.txt").write_text(snapshot_text, encoding="utf-8")
    (output_dir / "index.html").write_text(render_html(program), encoding="utf-8")

    if logo_source and logo_source.exists():
        destination_logo = assets_dir / "evo_logo.png"
        try:
            if logo_source.resolve() != destination_logo.resolve():
                shutil.copy2(logo_source, destination_logo)
        except FileNotFoundError:
            shutil.copy2(logo_source, destination_logo)


def render_html_from_program_file(program_path: Path) -> str:
    data = json.loads(program_path.read_text(encoding="utf-8"))
    return render_html(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the EvoStar 2026 friendly programme site.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Public EasyChair programme URL")
    parser.add_argument("--snapshot-file", help="Use a saved snapshot instead of fetching EasyChair")
    parser.add_argument("--output-dir", default="site", help="Directory where the static site will be written")
    parser.add_argument("--logo-file", default="evo_logo.png", help="Local logo file copied into the generated site")
    parser.add_argument("--min-sessions", type=int, default=0, help="Fail if fewer sessions are parsed")
    parser.add_argument("--min-talks", type=int, default=0, help="Fail if fewer talks are parsed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    logo_path = Path(args.logo_file)

    if args.snapshot_file:
        snapshot_text = Path(args.snapshot_file).read_text(encoding="utf-8")
        structured_text = extract_structured_from_snapshot(snapshot_text)
    else:
        html = fetch_html(args.url)
        structured_text = flatten_html_to_structured_text(html, args.url)
        snapshot_text = f"Source URL: {args.url}\n\nStructured Content:\n\n{structured_text}\n"

    program = parse_program(structured_text, args.url)

    if args.min_sessions and program["stats"]["sessions"] < args.min_sessions:
        raise ValueError(
            f"Parsed only {program['stats']['sessions']} sessions, below the safety threshold of {args.min_sessions}."
        )
    if args.min_talks and program["stats"]["talks"] < args.min_talks:
        raise ValueError(
            f"Parsed only {program['stats']['talks']} talks, below the safety threshold of {args.min_talks}."
        )

    build_site(program, snapshot_text, output_dir, logo_path)
    print(f"Built site in {output_dir} | sessions={program['stats']['sessions']} talks={program['stats']['talks']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
