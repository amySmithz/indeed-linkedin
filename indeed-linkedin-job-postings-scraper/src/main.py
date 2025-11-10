thonimport argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from utils.helpers import (
    setup_logging,
    load_json_file,
    fetch_html,
    merge_job_lists_dedup,
)
from extractors.indeed_parser import (
    build_indeed_search_url,
    parse_indeed_jobs,
)
from extractors.linkedin_parser import (
    build_linkedin_search_url,
    parse_linkedin_jobs,
)
from outputs.exporter import export_to_json

def _resolve_path(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p

def run_scraper(
    input_config_path: Path,
    output_path: Path,
    logger: logging.Logger,
) -> None:
    if not input_config_path.exists():
        logger.error("Input configuration file does not exist: %s", input_config_path)
        raise FileNotFoundError(f"Input configuration file not found: {input_config_path}")

    config = load_json_file(input_config_path)
    logger.debug("Loaded input configuration: %s", config)

    queries: List[Dict[str, Any]] = config.get("queries", [])
    if not queries:
        logger.warning("No queries provided in configuration. Nothing to do.")
        return

    proxy_cfg = config.get("proxy") or {}
    proxies = {
        "http": proxy_cfg.get("http"),
        "https": proxy_cfg.get("https"),
    } if proxy_cfg else None

    request_delay = float(config.get("request_delay_seconds", 1.0))
    user_agent = config.get("user_agent") or (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    headers = {
        "User-Agent": user_agent,
        "Accept-Language": "en-US,en;q=0.9",
    }

    all_results: List[Dict[str, Any]] = []
    session_counter = 0

    for query_cfg in queries:
        title = query_cfg.get("title") or query_cfg.get("keyword") or ""
        if not title:
            logger.warning("Skipping query without title/keyword: %s", query_cfg)
            continue

        locations = query_cfg.get("locations") or []
        if not locations:
            logger.warning("Query '%s' has no locations. Skipping.", title)
            continue

        platforms = [p.lower() for p in query_cfg.get("platforms", ["indeed", "linkedin"])]
        job_types = [jt.lower() for jt in query_cfg.get("job_types", [])]
        remote_flags = [r.lower() for r in query_cfg.get("remote", [])]
        max_results = int(query_cfg.get("max_results", 50))

        logger.info(
            "Processing query '%s' for %d locations on platforms: %s",
            title,
            len(locations),
            ", ".join(platforms),
        )

        for loc in locations:
            city = loc.get("city", "")
            country = loc.get("country", "")
            logger.info("Location: city='%s', country='%s'", city, country)

            # INDEED
            if "indeed" in platforms:
                indeed_url = build_indeed_search_url(
                    keyword=title,
                    city=city,
                    country=country,
                    job_types=job_types,
                    remote_flags=remote_flags,
                )
                logger.info("Indeed search URL: %s", indeed_url)

                try:
                    html = fetch_html(
                        indeed_url,
                        headers=headers,
                        proxies=proxies,
                        timeout=20,
                        logger=logger,
                    )
                    indeed_jobs = parse_indeed_jobs(
                        html,
                        max_results=max_results,
                        logger=logger,
                    )
                    logger.info(
                        "Parsed %d Indeed jobs for '%s' in %s, %s",
                        len(indeed_jobs),
                        title,
                        city,
                        country,
                    )
                    all_results.extend(indeed_jobs)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to scrape Indeed for '%s': %s", title, exc)

                session_counter += 1
                if request_delay > 0:
                    logger.debug("Sleeping %.2f seconds between requests.", request_delay)
                    time.sleep(request_delay)

            # LINKEDIN
            if "linkedin" in platforms:
                linkedin_url = build_linkedin_search_url(
                    keyword=title,
                    city=city,
                    country=country,
                    job_types=job_types,
                    remote_flags=remote_flags,
                )
                logger.info("LinkedIn search URL: %s", linkedin_url)

                try:
                    html = fetch_html(
                        linkedin_url,
                        headers=headers,
                        proxies=proxies,
                        timeout=20,
                        logger=logger,
                    )
                    linkedin_jobs = parse_linkedin_jobs(
                        html,
                        max_results=max_results,
                        logger=logger,
                    )
                    logger.info(
                        "Parsed %d LinkedIn jobs for '%s' in %s, %s",
                        len(linkedin_jobs),
                        title,
                        city,
                        country,
                    )
                    all_results.extend(linkedin_jobs)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to scrape LinkedIn for '%s': %s", title, exc)

                session_counter += 1
                if request_delay > 0:
                    logger.debug("Sleeping %.2f seconds between requests.", request_delay)
                    time.sleep(request_delay)

    if not all_results:
        logger.warning("No jobs collected. Nothing to export.")
        return

    logger.info("Merging and de-duplicating %d collected job records.", len(all_results))
    merged = merge_job_lists_dedup(all_results)
    logger.info("After de-duplication, %d unique job records remain.", len(merged))

    export_to_json(merged, output_path, logger=logger)
    logger.info("Export completed to %s", output_path)
    logger.info("Total HTTP request sessions: %d", session_counter)

def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Indeed + LinkedIn Job Postings Scraper",
    )
    parser.add_argument(
        "-i",
        "--input",
        default="data/inputs.sample.json",
        help="Path to input configuration JSON (default: data/inputs.sample.json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="data/sample_output.json",
        help="Path to output JSON file (default: data/sample_output.json)",
    )
    parser.add_argument(
        "-l",
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args(argv)

    logger = setup_logging(level=args.log_level)

    project_root = Path(__file__).resolve().parents[1]
    input_path = _resolve_path(args.input)
    if not input_path.is_absolute():