thonfrom __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests
from requests import Response, Session

def setup_logging(level: str = "INFO") -> logging.Logger:
    """
    Configure a root logger with a reasonable default format.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger("job_scraper")
    logger.setLevel(numeric_level)

    # Avoid adding multiple handlers if called more than once
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

def load_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _create_session() -> Session:
    session = requests.Session()
    # Keep-alive is default; we can tune adapters here if needed.
    return session

def fetch_html(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    proxies: Optional[Dict[str, str]] = None,
    timeout: float = 20.0,
    max_retries: int = 3,
    backoff_factor: float = 1.5,
    logger: Optional[logging.Logger] = None,
) -> str:
    """
    Fetch HTML content from a URL with retry and basic error handling.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    session = _create_session()
    attempt = 0
    last_exc: Exception | None = None

    while attempt < max_retries:
        attempt += 1
        try:
            logger.debug(
                "HTTP GET %s (attempt %d/%d)",
                url,
                attempt,
                max_retries,
            )
            resp: Response = session.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            logger.debug(
                "Received response %s with %d bytes.",
                resp.status_code,
                len(resp.content),
            )
            return resp.text
        except (requests.RequestException, Exception) as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Request to %s failed on attempt %d/%d: %s",
                url,
                attempt,
                max_retries,
                exc,
            )
            if attempt < max_retries:
                sleep_time = backoff_factor ** (attempt - 1)
                logger.debug("Sleeping %.2f seconds before retry.", sleep_time)
                time.sleep(sleep_time)

    msg = f"Failed to fetch {url} after {max_retries} attempts"
    logger.error(msg)
    if last_exc:
        raise RuntimeError(msg) from last_exc
    raise RuntimeError(msg)

def merge_job_lists_dedup(jobs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge multiple job lists into a de-duplicated list based on job link.

    If multiple records share the same 'link', the first one wins.
    """
    seen_links: set[str] = set()
    merged: List[Dict[str, Any]] = []

    for job in jobs:
        link = job.get("link") or ""
        key = link.strip()
        if not key:
            # Jobs without a link are kept but deduped by a hash of fields
            key = json.dumps(
                {
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "location": job.get("location"),
                },
                sort_keys=True,
            )

        if key in seen_links:
            continue

        seen_links.add(key)
        merged.append(job)

    return merged