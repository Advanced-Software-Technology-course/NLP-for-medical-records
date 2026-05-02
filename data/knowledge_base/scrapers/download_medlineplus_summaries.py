"""
Download MedlinePlus health topic summaries (public domain) and write to a KB file.

Notes:
- Uses the MedlinePlus XML files list to locate the latest compressed topics file.
- Extracts title, full summary, alt titles (aka), and URL.
- Output is ASCII-only by default to align with repo conventions.

Usage:
  python download_medlineplus_summaries.py \
    --out ../medlineplus_summaries.txt \
    --max-topics 200 \
    --terms-file ../medlineplus_terms.txt
"""

import argparse
import io
import os
import re
import sys
import zipfile
from html import unescape
from urllib.request import urlopen
import xml.etree.ElementTree as ET

XML_INDEX_URL = "https://medlineplus.gov/xml.html"
DEFAULT_OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "medlineplus_summaries.txt"))


def _read_text(url: str, timeout: int = 30) -> str:
    with urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _find_latest_zip(html: str) -> str:
    matches = re.findall(r"https://medlineplus.gov/xml/mplus_topics_compressed_\d{4}-\d{2}-\d{2}\.zip", html)
    if not matches:
        raise RuntimeError("Could not locate the MedlinePlus compressed topics ZIP link.")
    return matches[0]


def _ascii_clean(text: str) -> str:
    if not text:
        return ""
    # Strip HTML tags and normalize whitespace.
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Enforce ASCII only to match repo conventions.
    return text.encode("ascii", "ignore").decode("ascii")


def _text_from_node(node: ET.Element) -> str:
    if node is None:
        return ""
    parts = []
    for txt in node.itertext():
        if txt:
            parts.append(txt)
    return _ascii_clean(" ".join(parts))


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _first_child_text(parent: ET.Element, child_name: str) -> str:
    for child in list(parent):
        if _local_name(child.tag) == child_name:
            return _text_from_node(child)
    return ""


def _all_child_text(parent: ET.Element, child_name: str) -> list[str]:
    out: list[str] = []
    for child in list(parent):
        if _local_name(child.tag) == child_name:
            val = _text_from_node(child)
            if val:
                out.append(val)
    return out


def _first_descendant_text(parent: ET.Element, child_name: str) -> str:
    for child in parent.iter():
        if _local_name(child.tag) == child_name:
            return _text_from_node(child)
    return ""


def _load_terms(path: str) -> list[str]:
    if not path:
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    return [ln.lower() for ln in raw]


def _topic_matches(term_list: list[str], title: str, summary: str, alt_titles: list[str]) -> bool:
    if not term_list:
        return True
    hay = " ".join([title] + alt_titles + [summary]).lower()
    return any(term in hay for term in term_list)


def _parse_topics(
    xml_bytes: bytes,
    term_list: list[str],
    max_topics: int | None,
    debug: bool = False,
) -> list[dict]:
    topics = []
    seen_topics = 0
    missing_fields = 0
    # Use iterparse to keep memory usage low.
    context = ET.iterparse(io.BytesIO(xml_bytes), events=("end",))
    for event, elem in context:
        if _local_name(elem.tag) == "health-topic":
            seen_topics += 1
            title = _ascii_clean(elem.attrib.get("title", ""))
            url = _ascii_clean(elem.attrib.get("url", ""))
            summary = _first_child_text(elem, "full-summary") or _first_descendant_text(elem, "full-summary")
            alt_titles = _all_child_text(elem, "also-called")
            if not alt_titles:
                alt_titles = _all_child_text(elem, "alt-title")

            if not title or not summary:
                missing_fields += 1
                if debug and seen_topics <= 3:
                    print(f"[MedlinePlus][debug] Missing title/summary for topic {seen_topics}")
                elem.clear()
                continue

            if not _topic_matches(term_list, title, summary, alt_titles):
                elem.clear()
                continue

            topics.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "alt_titles": alt_titles,
                }
            )

            elem.clear()
            if max_topics and len(topics) >= max_topics:
                break
    if debug:
        print(f"[MedlinePlus][debug] Parsed topics: {seen_topics}, missing title/summary: {missing_fields}")
    return topics


def _write_output(out_path: str, topics: list[dict]) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# MedlinePlus Health Topic Summaries (Public Domain)\n")
        f.write("# Source: MedlinePlus, National Library of Medicine\n\n")
        for topic in topics:
            f.write(f"TOPIC: {topic['title']}\n")
            if topic["alt_titles"]:
                f.write("ALSO CALLED: " + "; ".join(topic["alt_titles"]) + "\n")
            if topic["url"]:
                f.write(f"URL: {topic['url']}\n")
            f.write(f"SUMMARY: {topic['summary']}\n")
            f.write("SOURCE: MedlinePlus, National Library of Medicine\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download MedlinePlus health topic summaries.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output text file path")
    parser.add_argument("--url", default="", help="Override the XML zip URL")
    parser.add_argument("--terms-file", default="", help="Optional newline-delimited filter terms")
    parser.add_argument("--max-topics", type=int, default=0, help="Optional limit for topics")
    parser.add_argument("--debug", action="store_true", help="Print debug parsing stats")
    args = parser.parse_args()

    html = _read_text(XML_INDEX_URL)
    zip_url = args.url or _find_latest_zip(html)
    print(f"[MedlinePlus] Using zip: {zip_url}")

    xml_bytes = None
    with urlopen(zip_url, timeout=60) as resp:
        zdata = resp.read()

    with zipfile.ZipFile(io.BytesIO(zdata)) as zf:
        xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
        if not xml_names:
            raise RuntimeError("No XML file found in MedlinePlus zip.")
        xml_bytes = zf.read(xml_names[0])

    term_list = _load_terms(args.terms_file)
    max_topics = args.max_topics if args.max_topics > 0 else None

    topics = _parse_topics(xml_bytes, term_list, max_topics, debug=args.debug)
    _write_output(args.out, topics)
    print(f"[MedlinePlus] Wrote {len(topics)} topics to {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[MedlinePlus] Failed: {exc}")
        raise
