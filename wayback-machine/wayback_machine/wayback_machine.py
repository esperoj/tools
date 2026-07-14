"""Core Wayback Machine client implementation."""

import concurrent.futures
import os
import threading
import time
from typing import Any, Callable, Iterable

from curl import CurlExecutor, CurlRequest


class WaybackMachine:
    """SDK for the Internet Archive's Wayback Machine APIs.

    Provides methods for saving URLs (SPN2), with a foundation designed to
    support CDX querying and Availability/Index checking in the future.
    """

    SPN2_DEFAULT_OPTS = {
        "capture_all": 0,
        "capture_outlinks": 0,
        "email_result": 1,
        "force_get": 1,
        "skip_first_archive": 1,
    }

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        proxy_prefix: str = "https://sjc-proxy.esperoj.workers.dev/",
        max_workers: int = 4,
        dry_run: bool = False,
    ):
        """Initializes the Wayback Machine client."""
        self.dry_run = dry_run
        self.proxy_prefix = proxy_prefix
        self.max_workers = max_workers

        self.api_key = api_key or os.getenv("INTERNET_ARCHIVE_ACCESS_KEY")
        self.api_secret = api_secret or os.getenv(
            "INTERNET_ARCHIVE_SECRET_KEY"
        )

    def _get_spn2_headers(self) -> dict[str, str]:
        """Headers required specifically for authenticated SPN2 endpoints."""
        if not self.dry_run and not (self.api_key and self.api_secret):
            raise ValueError(
                "Save/SPN2 features require INTERNET_ARCHIVE_ACCESS_KEY and SECRET_KEY."
            )
        return {
            "Accept": "application/json",
            "Authorization": f"LOW {self.api_key}:{self.api_secret}",
        }

    def _curl(
        self,
        executor: CurlExecutor,
        url: str,
        method: str = "GET",
        headers: dict = None,
        data: Any = None,
    ) -> dict:
        """Centralized HTTP request helper using the CurlExecutor."""
        target_url = f"{self.proxy_prefix}{url}" if self.proxy_prefix else url
        req = CurlRequest(
            url=target_url,
            method=method,
            headers=headers or {},
            data=data,
            timeout=120,
        )
        res = list(executor.execute([req]))[0]
        if not res.ok:
            raise RuntimeError(f"HTTP {res.status_code}: {res.error}")

        try:
            return res.json()
        except Exception:
            return {"raw_response": res.content}

    # =========================================================================
    # SPN2 (SAVE) API
    # =========================================================================

    def save_batch(
        self,
        jobs: Iterable[dict[str, Any] | str],
        default_options: dict[str, Any] | None = None,
        on_event: Callable[[str, int, str, str], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Archives a batch of URLs concurrently via the SPN2 API.

        Args:
            jobs: Iterable of URLs (strings) or config dicts (e.g., {"url": "...", "capture_outlinks": 1}).
            default_options: Fallback SPN2 settings.
            on_event: Progress callback signature `(url, slot, status, message)`.
        """
        defaults = {**self.SPN2_DEFAULT_OPTS, **(default_options or {})}
        results = []
        slots = list(range(self.max_workers))
        lock = threading.Lock()

        def _worker(job_input: dict | str) -> dict:
            job = (
                {"url": job_input} if isinstance(job_input, str) else job_input
            )
            url = job["url"]
            opts = {**defaults, **{k: v for k, v in job.items() if k != "url"}}

            with lock:
                slot = slots.pop(0)
            res_data = {"url": url, "archive_url": None, "error": None}

            try:
                if on_event:
                    on_event(url, slot, "INIT", "Starting save job")
                url_res = self._save_single(url, opts, slot, on_event)
                res_data["archive_url"] = url_res
                if on_event:
                    on_event(url, slot, "OK", url_res)
            except Exception as e:
                res_data["error"] = str(e)
                if on_event:
                    on_event(url, slot, "FAIL", str(e))
            finally:
                with lock:
                    slots.append(slot)

            return res_data

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as pool:
            for res in pool.map(_worker, jobs):
                results.append(res)

        return results

    def _save_single(
        self, url: str, opts: dict, slot: int, on_event: Callable | None
    ) -> str:
        """Internal multistep SPN2 pipeline for a single URL."""
        if self.dry_run:
            if on_event:
                on_event(url, slot, "SAVE", "Simulating API request...")
            time.sleep(1.5)
            return f"https://web.archive.org/web/20260101000000id_/{url}"

        executor = CurlExecutor(max_workers=1)
        headers = self._get_spn2_headers()
        sleep_dynamic = max(10, self.max_workers * 2)

        # 1. WAIT: Check availability queue
        start_time = time.time()
        while True:
            if time.time() - start_time > 900:
                raise RuntimeError("Timeout waiting for SPN2 queue.")
            if on_event:
                on_event(url, slot, "WAIT", "Checking account availability...")

            status_data = self._curl(
                executor,
                f"https://web.archive.org/save/status/user?_t={int(time.time())}",
                headers=headers,
            )
            if status_data.get("available", 0) >= 2:
                break
            time.sleep(sleep_dynamic)

        # 2. SAVE: Submit URL to be archived
        if on_event:
            on_event(url, slot, "SAVE", "Submitting to archive queue...")
        save_res = self._curl(
            executor,
            "https://web.archive.org/save",
            method="POST",
            headers=headers,
            data={"url": url, **opts},
        )
        job_id = save_res.get("job_id")
        if not job_id:
            raise RuntimeError(f"Missing job_id in SPN2 response: {save_res}")

        # 3. POLL: Wait for completion
        start_time = time.time()
        while True:
            if time.time() - start_time > 960:
                raise RuntimeError("Timeout polling job status.")
            if on_event:
                on_event(
                    url,
                    slot,
                    "POLL",
                    f"Polling job {job_id} [{int(time.time() - start_time)}s]",
                )

            poll_data = self._curl(
                executor,
                f"https://web.archive.org/save/status/{job_id}",
                headers=headers,
            )
            st = poll_data.get("status")

            if st == "success":
                return f"https://web.archive.org/web/{poll_data['timestamp']}id_/{poll_data['original_url']}"
            elif st == "pending":
                time.sleep(20)
            else:
                raise RuntimeError(f"SPN2 Job failed with status: '{st}'")

    # =========================================================================
    # FOUNDATION FOR FUTURE FEATURES
    # =========================================================================

    def check_index(self, url: str) -> dict:
        """Placeholder for the Wayback Availability JSON API."""
        raise NotImplementedError(
            "Index checking will be implemented in a future release."
        )

    def search_cdx(self, query: str) -> list[dict]:
        """Placeholder for the CDX Server API."""
        raise NotImplementedError(
            "CDX querying will be implemented in a future release."
        )
