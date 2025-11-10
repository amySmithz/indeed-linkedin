thonfrom __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List

from bs4 import BeautifulSoup  # type: ignore[import-untyped]

def build_linkedin_search_url(
    keyword: str,
    city: str = "",
    country: str = "",
    job_types: List[str] | None = None,
    remote_flags: List[str] | None = None,
) -> str:
    """
    Build a basic LinkedIn Jobs search URL.

    This targets the public LinkedIn job search page. Real-world usage should
    respect robots.txt, terms of service, and rate limits.
    """
    base = "https://www.linkedin.com/jobs/search/"
    params: Dict[str, Any] = {
        "keywords": keyword,
    }

    location_bits = []
    if city:
        location_bits.append(city)
    if country:
        location_bits.append(country)
    if location_bits:
        params["location"] = ", ".join(location_bits)

    # Job type filter via 'f_JT' (comma-separated codes like F, P, C, I, T).
    jt_map = {
        "full-time": "F",
        "fulltime": "F",
        "part-time": "P",
        "parttime": "P",
        "contract": "C",
        "internship": "I",
        "temporary": "T",
    }
    if job_types:
        codes = [jt_map[jt] for jt in job_types if jt in jt_map]
        if codes:
            params["f_JT"] = ",".join(codes)

    # Remote / on-site filter via 'f_WT' (1=On-site, 2=Remote, 3=Hybrid)
    if remote_flags:
        flags = [f.lower() for f in remote_flags]
        wt_codes = []
        if any(f in flags for f in ["yes", "remote"]):
            wt_codes.append("2")
        if any(f in flags for f in ["no", "onsite", "on-site"]):
            wt_codes.append("1")
        if any("hybrid" in f for f in flags):
            wt_codes.append("3")
        if wt_codes:
            params["f_WT"] = ",".join(wt_codes)

    return f"{base}?{urllib.parse.urlencode(params)}"

def _parse_relative_date(date_str: str) -> str:
    """
    Convert LinkedIn-style relative date text into an ISO date.

    Examples:
        '1 day ago' / '2 weeks ago' / '5 hours ago'
    """
    date_str = date_str.strip().lower()
    today = datetime.utcnow().date()

    if not date_str:
        return today.isoformat()

    for needle in ["hour", "hours", "minute", "minutes"]:
        if needle in date_str:
            return today.isoformat()

    if "today" in date_str:
        return today.isoformat()

    if "yesterday" in date_str:
        return (today - timedelta(days=1)).isoformat()

    # Generic "x days/weeks ago"
    parts = date_str.split()
    try:
        num = int(parts[0])
    except (ValueError, IndexError):
        return today.isoformat()

    unit = parts[1] if len(parts) > 1 else "days"
    if "week" in unit:
        delta_days = num * 7
    elif "month" in unit:
        delta_days = num * 30
    else:
        delta_days = num

    return (today - timedelta(days=delta_days)).isoformat()

def parse_linkedin_jobs(
    html: str,
    max_results: int = 50,
    logger: logging.Logger | None = None,
) -> List[Dict[str, Any]]:
    """
    Parse LinkedIn job search HTML page into structured records.

    Each dict contains:
        title, company, location, jobtype, remote, posted_date,
        link, description, salary, source
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    soup = BeautifulSoup(html, "lxml")

    # Main selector for job results. LinkedIn uses several layout variants,
    # so we test a few.
    cards = soup.select("li.jobs-search-results__list-item")
    if not cards:
        cards = soup.select("li.jobs-search-results__list-item--active")
    if not cards:
        cards = soup.select("div.base-card")  # fallback for newer UI variants
    if not cards:
        logger.warning("No LinkedIn job cards found with known selectors.")
        return []

    jobs: List[Dict[str, Any]] = []

    for card in cards:
        if len(jobs) >= max_results:
            break

        try:
            title_el = (
                card.select_one("h3.base-search-card__title")
                or card.select_one("a.job-card-list__title")
                or card.select_one("a.base-card__full-link")
            )
            title = title_el.get_text(strip=True) if title_el else ""

            company_el = card.select_one("h4.base-search-card__subtitle a") or card.select_one(
                "a.job-card-container__company-name",
            )
            company = company_el.get_text(strip=True) if company_el else ""

            location_el = card.select_one("span.job-search-card__location")
            location = location_el.get_text(strip=True) if location_el else ""

            link = ""
            if title_el and title_el.name == "a" and title_el.has_attr("href"):
                link = title_el["href"]
            else:
                link_el = card.select_one("a.base-card__full-link") or card.select_one(
                    "a.job-card-list__title",
                )
                if link_el and link_el.has_attr("href"):
                    link = link_el["href"]

            # Meta info: job type / remote indicator
            jobtype = ""
            remote = "Unknown"
            description = ""
            salary = None

            # Job insights / meta lines
            insights_els = card.select("ul.job-card-container__metadata-items li") or card.select(
                "div.job-search-card__benefits span",
            )
            for el in insights_els:
                text = el.get_text(" ", strip=True)
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
                if "on-site" in lower or "on site" in lower:
                    remote = "No"

                if any(symbol in text for symbol in ["$", "€", "£"]):
                    salary = text

            # Posted date
            date_el = card.select_one("time")
            posted_date_raw = date_el.get_text(strip=True) if date_el else ""
            posted_date = _parse_relative_date(posted_date_raw)

            # Description is not always present on listing cards; best-effort:
            desc_el = card.select_one("p.job-search-card__snippet")
            if desc_el:
                description = desc_el.get_text(" ", strip=True)

            if not title and not company and not link:
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
                "salary": salary,
                "source": "LinkedIn",
            }

            jobs.append(job)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error while parsing a LinkedIn job card: %s", exc)

    return jobs