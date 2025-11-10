thonfrom __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List

from bs4 import BeautifulSoup  # type: ignore[import-untyped]

def build_indeed_search_url(
    keyword: str,
    city: str = "",
    country: str = "",
    job_types: List[str] | None = None,
    remote_flags: List[str] | None = None,
) -> str:
    """
    Build a basic Indeed search URL.

    This uses the public web UI query parameters. It is intentionally simple and
    may need tuning for heavy use, but works for typical search scenarios.
    """
    base = "https://www.indeed.com/jobs"
    query_params: Dict[str, Any] = {
        "q": keyword,
    }

    location_bits = []
    if city:
        location_bits.append(city)
    if country:
        location_bits.append(country)
    if location_bits:
        query_params["l"] = ", ".join(location_bits)

    if job_types:
        # Indeed supports "jt" with values like "fulltime", "parttime", etc.
        jt_map = {
            "full-time": "fulltime",
            "fulltime": "fulltime",
            "part-time": "parttime",
            "parttime": "parttime",
            "contract": "contract",
            "internship": "internship",
            "temporary": "temporary",
        }
        translated = [jt_map[jt] for jt in job_types if jt in jt_map]
        if translated:
            # Just pick the first, to keep it simple.
            query_params["jt"] = translated[0]

    if remote_flags:
        # Indeed offers remote filter via "sc" parameter, which is somewhat opaque.
        # For now, we just encode a keyword for remote searches.
        if "yes" in remote_flags or "remote" in remote_flags:
            query_params["sc"] = "0kf%3Ajt(telecommute)%3B"

    return f"{base}?{urllib.parse.urlencode(query_params)}"

def _parse_relative_date(date_str: str) -> str:
    """
    Convert Indeed-style relative date strings into ISO date (YYYY-MM-DD).

    Examples:
        'Just posted' -> today
        'Today' -> today
        '1 day ago' -> today - 1
        '30+ days ago' -> today - 30
    """
    date_str = date_str.strip().lower()
    today = datetime.utcnow().date()

    if not date_str:
        return today.isoformat()

    if "today" in date_str or "just posted" in date_str:
        return today.isoformat()

    if "30+" in date_str:
        return (today - timedelta(days=30)).isoformat()

    if "day" in date_str:
        # '1 day ago' / '3 days ago'
        parts = date_str.split()
        try:
            num = int(parts[0])
            return (today - timedelta(days=num)).isoformat()
        except (ValueError, IndexError):
            return today.isoformat()

    # Fallback: return today
    return today.isoformat()

def parse_indeed_jobs(
    html: str,
    max_results: int = 50,
    logger: logging.Logger | None = None,
) -> List[Dict[str, Any]]:
    """
    Parse Indeed job results from HTML into a list of structured dictionaries.

    Each dict contains:
        title, company, location, jobtype, remote, posted_date,
        link, description, salary, source
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    soup = BeautifulSoup(html, "lxml")

    # As of late 2024, Indeed uses 'td.resultContent' inside 'tr.job_seen_beacon',
    # but this has changed historically. We try a few selectors and merge.
    cards = soup.select("div.job_seen_beacon")
    if not cards:
        cards = soup.select("td.resultContent")
    if not cards:
        logger.warning("No Indeed job cards found using known selectors.")
        return []

    jobs: List[Dict[str, Any]] = []

    for card in cards:
        if len(jobs) >= max_results:
            break

        try:
            # Title & link
            title_el = card.select_one("h2.jobTitle a") or card.select_one("a.tapItem")
            title = title_el.get_text(strip=True) if title_el else ""
            link = ""
            if title_el and title_el.has_attr("href"):
                href = title_el["href"]
                if href.startswith("/"):
                    link = f"https://www.indeed.com{href}"
                else:
                    link = href

            # Company
            company_el = card.select_one("span.companyName")
            company = company_el.get_text(strip=True) if company_el else ""

            # Location
            location_el = card.select_one("div.companyLocation") or card.select_one("span.companyLocation")
            location = location_el.get_text(" ", strip=True) if location_el else ""

            # Summary / description
            desc_el = card.select_one("div.job-snippet")
            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            # Salary
            salary_el = card.select_one("div.salary-snippet") or card.select_one("span.salary-snippet-container")
            salary = salary_el.get_text(" ", strip=True) if salary_el else ""

            # Job type & remote tag (best-effort)
            jobtype = ""
            remote = "Unknown"
            badge_texts = [
                el.get_text(" ", strip=True)
                for el in card.select("div.attribute_snippet") + card.select("div.metadata")
            ]
            for text in badge_texts:
                lower = text.lower()
                if any(t in lower for t in ["full-time", "full time"]):
                    jobtype = "Full-time"
                elif any(t in lower for t in ["part-time", "part time"]):
                    jobtype = "Part-time"
                elif "contract" in lower:
                    jobtype = "Contract"
                elif "internship" in lower:
                    jobtype = "Internship"

                if "remote" in lower:
                    remote = "Yes"

            if remote == "Unknown":
                if any("on-site" in t.lower() or "on site" in t.lower() for t in badge_texts):
                    remote = "No"

            # Posted date
            date_el = card.select_one("span.date") or card.select_one("span.dateStamp")
            posted_date_raw = date_el.get_text(strip=True) if date_el else ""
            posted_date = _parse_relative_date(posted_date_raw)

            if not title and not company and not link:
                # Skip obviously empty entries
                continue

            job = {
                "title": title,
                "company": company,
                "location": location,
                "jobtype": jobtype or None,
                "remote": remote,
                "posted_date": posted_date,
                "link": link,
                "description": description,
                "salary": salary or None,
                "source": "Indeed",
            }

            jobs.append(job)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error while parsing an Indeed job card: %s", exc)

    return jobs