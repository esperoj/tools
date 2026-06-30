"""Module for orchestrating concurrent network downloads using native curl.

This module leverages curl's parallel execution engine (-Z) using transient
configuration files. It eliminates Python multi-threading bottlenecks by merging Wait
and I/O streams, parsing progress updates, and outputting structured performance data.

It also provides a high-level, ergonomic API inspired by `requests` and `httpx` for
simple, synchronous HTTP tasks.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


@dataclass
class CurlRequest:
    """Represents a targeted HTTP request payload destination configuration.

    Attributes:
        url (str): The target remote asset URL.
        output_path (str | Path): Local filesystem path where the resource will be preserved.
        method (str): The HTTP verb to use for the transaction. Defaults to "GET".
        headers (dict[str, str]): Outbound request headers as key-value pairs.
        data (object): Raw text string or raw bytes to pass as standard body content.
        json_data (object): Arbitrary structured data payload sent as application/json.
        options (dict[str, object]): Dictionary of native per-request curl override options.
    """
    url: str
    output_path: str | Path
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    data: object = None
    json_data: object = None
    options: dict[str, object] = field(default_factory=dict)


class CurlPlugin:
    """Base class for intercepting and modifying requests and results.
    
    Inspired by transporters and event hooks in requests/httpx, plugins allow
    you to build reusable logic to mutate requests before they are sent and
    transform results as they stream back.
    """
    
    def modify_request(self, request: CurlRequest) -> CurlRequest:
        return request
        
    def modify_result(self, result: dict[str, object]) -> dict[str, object]:
        return result


class Response:
    """High-level response object inspired by requests/httpx.
    
    Provides easy access to the downloaded data in various formats.
    """
    def __init__(self, status_code: int, url: str, content: bytes, metrics: dict[str, Any]):
        self.status_code = status_code
        self.url = url
        self.content = content
        self.metrics = metrics

    @property
    def text(self) -> str:
        """Returns the response body as a string."""
        return self.content.decode('utf-8', errors='replace')

    def json(self) -> Any:
        """Parses the response body as JSON."""
        return json.loads(self.content)
        
    def raise_for_status(self):
        """Raises an exception if the HTTP status code is an error (4xx, 5xx)."""
        if 400 <= self.status_code < 600:
            raise Exception(f"HTTP Error {self.status_code} for url: {self.url}")

    def __repr__(self) -> str:
        return f"<Response [{self.status_code}]>"


class ParallelCurlRunner:
    """Orchestrates native parallel curl processes using configuration engines."""

    def __init__(
        self, 
        max_parallel: int = 5, 
        global_options: dict[str, object] | None = None,
        plugins: list[CurlPlugin] | None = None
    ):
        self.max_parallel = max_parallel
        self.global_options = global_options if global_options is not None else {
            "location": True,
            "fail": False,
            "connect-timeout": 30,
            "retry": 3,
            "retry-connrefused": True,
        }
        self.plugins = plugins or []

    def execute(self, requests: Iterable[CurlRequest]) -> Iterator[dict[str, object]]:
        req_list = []
        for req in requests:
            for plugin in self.plugins:
                req = plugin.modify_request(req)
            req_list.append(req)

        if not req_list:
            return

        yield {"event": "init", "total": len(req_list)}

        with tempfile.TemporaryDirectory(prefix="perma_curl_") as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "curl_config.txt"

            self._build_config_file(config_file, temp_path, req_list)

            with subprocess.Popen(
                ["curl", "-K", str(config_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            ) as proc:
                if proc.stdout:
                    buf = []
                    while True:
                        char = proc.stdout.read(1)
                        if not char and proc.poll() is not None:
                            break
                        if char in ("\r", "\n"):
                            line = "".join(buf).strip()
                            buf.clear()
                            if line:
                                if line.startswith("{"):
                                    res = self._process_result(line)
                                    if res: 
                                        yield res
                                elif "XFR:" in line:
                                    progress_data = self._parse_parallel_progress(line)
                                    if progress_data:
                                        yield {"event": "progress", "data": progress_data}
                        else:
                            buf.append(char)
                    
                    if buf:
                        line = "".join(buf).strip()
                        if line.startswith("{"):
                            res = self._process_result(line)
                            if res: 
                                yield res
                proc.wait()

    def _process_result(self, line: str) -> dict[str, object] | None:
        try:
            raw_data = json.loads(line)
            metric_data: dict[str, object] = {
                "url": raw_data.get("url_effective"),
                "status": raw_data.get("http_code") or raw_data.get("response_code"),
                "size_bytes": raw_data.get("size_download"),
                "speed_bytes_sec": raw_data.get("speed_download"),
                "time_seconds": raw_data.get("time_total"),
                "content_type": raw_data.get("content_type"),
                "_raw_curl_metrics": raw_data
            }

            for plugin in self.plugins:
                metric_data = plugin.modify_result(metric_data)
            return {"event": "result", "data": metric_data}
        except json.JSONDecodeError:
            return None

    def _parse_parallel_progress(self, line: str) -> dict[str, object] | None:
        normalized = line.replace("DL:", " DL ").replace("UL:", " UL ").replace("XFR:", " XFR ").replace("ETA:", " ETA ")
        parts = normalized.split()
        data = {
            "download_speed": "0 B",
            "upload_speed": "0 B",
            "completed_files": 0,
            "total_files": 0,
            "eta": "--:--:--"
        }
        try:
            for i in range(len(parts) - 1):
                if parts[i] == "DL":
                    data["download_speed"] = parts[i+1]
                    if i + 2 < len(parts) and parts[i+2] not in ("UL", "XFR", "ETA"):
                        data["download_speed"] += " " + parts[i+2]
                elif parts[i] == "UL":
                    data["upload_speed"] = parts[i+1]
                    if i + 2 < len(parts) and parts[i+2] not in ("XFR", "ETA"):
                        data["upload_speed"] += " " + parts[i+2]
                elif parts[i] == "XFR":
                    xfr = parts[i+1]
                    if "/" in xfr:
                        comp, tot = xfr.split("/", 1)
                        data["completed_files"] = int("".join(c for c in comp if c.isdigit()))
                        data["total_files"] = int("".join(c for c in tot if c.isdigit()))
                elif parts[i] == "ETA":
                    data["eta"] = parts[i+1]
            return data
        except Exception:
            return None

    def _build_config_file(self, config_file: Path, temp_path: Path, requests: list[CurlRequest]) -> None:
        with config_file.open("w", encoding="utf-8") as f:
            f.write("parallel\n")
            f.write(f"parallel-max = {self.max_parallel}\n")
            
            for key, val in self.global_options.items():
                f.write(self._format_opt(key, val))
            f.write("\n")

            for idx, req in enumerate(requests):
                f.write(f'url = "{req.url}"\n')
                
                out_p = Path(req.output_path)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                f.write(f'output = "{out_p.as_posix()}"\n')

                if req.method.upper() != "GET":
                    f.write(f'request = "{req.method.upper()}"\n')

                for k, v in req.headers.items():
                    escaped_v = v.replace('\\', '\\\\').replace('"', '\\"')
                    f.write(f'header = "{k}: {escaped_v}"\n')

                for key, val in req.options.items():
                    f.write(self._format_opt(key, val))

                if req.json_data is not None:
                    f.write('header = "Content-Type: application/json"\n')
                    p_file = temp_path / f"payload_{idx}.json"
                    p_file.write_text(json.dumps(req.json_data), encoding="utf-8")
                    f.write(f'data-binary = "@{p_file.as_posix()}"\n')
                elif req.data is not None:
                    p_file = temp_path / f"payload_{idx}.raw"
                    if isinstance(req.data, bytes):
                        p_file.write_bytes(req.data)
                    else:
                        p_file.write_text(str(req.data), encoding="utf-8")
                    f.write(f'data-binary = "@{p_file.as_posix()}"\n')

                f.write('write-out = "%{json}\\n"\n\n')

    @staticmethod
    def _format_opt(key: str, val: object) -> str:
        if isinstance(val, bool):
            return f"{key}\n" if val else f"no-{key}\n"
        if isinstance(val, (int, float)):
            return f"{key} = {val}\n"
        escaped_val = str(val).replace('\\', '\\\\').replace('"', '\\"')
        return f'{key} = "{escaped_val}"\n'


# ==============================================================================
# Ergonomic / Simple API (requests/httpx style)
# ==============================================================================

def request(method: str, url: str, **kwargs) -> Response:
    """Constructs and sends an HTTP request gracefully using curl.

    Args:
        method (str): HTTP Method (e.g. "GET", "POST").
        url (str): The URL to request.
        **kwargs: Optional arguments that `CurlRequest` takes (headers, data, json).

    Returns:
        Response: A populated Response object.
    """
    with tempfile.TemporaryDirectory(prefix="curl_simple_") as tmp_dir:
        out_path = Path(tmp_dir) / "output.bin"
        
        # Pop standard ergonomic keys matching the new kwargs
        headers = kwargs.pop("headers", {})
        data = kwargs.pop("data", None)
        json_data = kwargs.pop("json", None)
        options = kwargs.pop("options", {})
        plugins = kwargs.pop("plugins", None)

        req = CurlRequest(
            url=url, 
            output_path=out_path, 
            method=method.upper(), 
            headers=headers, 
            data=data, 
            json_data=json_data,
            options=options
        )
        
        runner = ParallelCurlRunner(max_parallel=1, plugins=plugins)
        
        result_data = {}
        for event in runner.execute([req]):
            if event["event"] == "result":
                result_data = event["data"]
        
        content = b""
        if out_path.exists():
            content = out_path.read_bytes()
            
        return Response(
            status_code=result_data.get("status", 0),
            url=result_data.get("url", url),
            content=content,
            metrics=result_data
        )

def get(url: str, **kwargs) -> Response:
    """Sends a GET request."""
    return request("GET", url, **kwargs)

def post(url: str, data: Any = None, json: Any = None, **kwargs) -> Response:
    """Sends a POST request."""
    return request("POST", url, data=data, json=json, **kwargs)

def put(url: str, data: Any = None, **kwargs) -> Response:
    """Sends a PUT request."""
    return request("PUT", url, data=data, **kwargs)

def patch(url: str, data: Any = None, **kwargs) -> Response:
    """Sends a PATCH request."""
    return request("PATCH", url, data=data, **kwargs)

def delete(url: str, **kwargs) -> Response:
    """Sends a DELETE request."""
    return request("DELETE", url, **kwargs)
