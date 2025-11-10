thonfrom __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

def export_to_json(
    jobs: Iterable[Dict[str, Any]],
    output_path: Path,
    logger: Optional[logging.Logger] = None,
) -> None:
    """
    Export job records as a JSON array to the given output path.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    job_list: List[Dict[str, Any]] = list(jobs)
    logger.debug("Preparing to export %d jobs to %s", len(job_list), output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(job_list, f, ensure_ascii=False, indent=2)

    logger.info("Wrote %d job records to %s", len(job_list), output_path)