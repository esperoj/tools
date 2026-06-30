# Python Curl Client

A high-performance Python HTTP client built natively on top of `curl`. 

It offers two distinct ways to work:
1. **The Simple API:** A drop-in replacement for everyday `requests` or `httpx` workflows.
2. **The Parallel Engine:** A robust parallel orchestrator that leverages `curl -Z` via configuration files to download hundreds of files simultaneously, bypassing the Python GIL and multi-threading bottlenecks entirely.

## Requirements
- Python 3.10+
- `curl` 7.70.0 or higher (required for native `%{json}` metric extractions)

---

## 1. Simple Usage (The Ergonomic API)

Borrowing from familiar libraries, you can execute standard HTTP verbs cleanly in just a few lines of code. It parses `.json()` and `.text` cleanly out of the box.

```python
import curl

# Perform a simple GET request
response = curl.get("https://httpbin.org/get")
print(response.status_code)  # 200
print(response.json())       # Parses the application/json dictionary

# Perform a POST request with structured JSON
response = curl.post(
    "https://httpbin.org/post",
    json={"hello": "world"},
    headers={"X-Custom-Header": "value"}
)
print(response.text)
```

---

## 2. Advanced Usage (The Parallel Orchestrator)

When you need to make 50, 100, or 10,000 requests, sequential `.get()` calls or standard Python ThreadPools often become the bottleneck. 

The `ParallelCurlRunner` compiles your request map into a transient curl manifest file and fires a single `curl -Z` subprocess. This delegates connection pooling, multiplexing, and async IO directly to curl's highly optimized C-backend.

```python
from curl import CurlRequest, ParallelCurlRunner

# 1. Define your payload and destinations
requests = [
    CurlRequest(url="https://httpbin.org/get", output_path="./output/get.json"),
    CurlRequest(url="https://httpbin.org/post", method="POST", json_data={"key": "value"}, output_path="./output/post.json")
]

# 2. Initialize the runner (defaults to 5 parallel connections)
runner = ParallelCurlRunner(max_parallel=2)

# 3. Stream events and results
for event in runner.execute(requests):
    if event["event"] == "init":
        print(f"Starting {event['total']} downloads...")
    elif event["event"] == "progress":
        print(f"Progress: {event['data']['completed_files']}/{event['data']['total_files']} files")
    elif event["event"] == "result":
        print(f"Success! Status: {event['data']['status']} | URL: {event['data']['url']}")
```

## The Plugin System (Hooks & Transports)

Inspired by the concept of "Event Hooks" in `httpx` and "Transports/Adapters" in `requests`, this module uses a simple `CurlPlugin` architecture to let you modify requests **before** they execute and transform results **after** they complete.

Plugins are incredibly powerful because they let you securely compose logic for:
- Prepending Web Proxies / Network transports
- Appending global Authorization headers
- Obfuscating logs / Transforming payloads

### Usage Example with Web Proxy

Here is how you inject the official `WebProxyPlugin` to proxy all of your requests cleanly.

```python
from curl import CurlRequest, ParallelCurlRunner
from curl.plugins.proxy import WebProxyPlugin

# 1. Initialize the plugin (defaults to https://proxy.esperoj.eu.org/)
proxy_plugin = WebProxyPlugin(proxy_prefix="https://proxy.esperoj.eu.org/")

# 2. Attach the plugin to the runner via the `plugins` array
runner = ParallelCurlRunner(
    max_parallel=3,
    plugins=[proxy_plugin]
)

# 3. Create normal requests (the URL remains clean in your code!)
requests = [
    CurlRequest(url="https://ipwho.de", output_path="./ipwho.txt"),
    CurlRequest(url="https://ipinfo.io/json", output_path="./ipinfo.txt")
]

# 4. Execute the stream 
for event in runner.execute(requests):
    if event["event"] == "result":
        print(f"Completed {event['data']['url']} with status {event['data']['status']}")
```

## Advanced Data Metrics

Because this library leverages curl's native `%{json}` formatter, every single result payload—even in the simple `response.metrics` object—automatically includes a `_raw_curl_metrics` dictionary containing extreme detail about the transaction without standard Python string escaping bugs.

```python
{
    "url": "https://httpbin.org/get",
    "status": 200,
    "size_bytes": 302,
    "speed_bytes_sec": 1250,
    "time_seconds": 0.241,
    "content_type": "application/json",
    "_raw_curl_metrics": {
        "remote_ip": "18.232.227.86",
        "remote_port": 443,
        "ssl_verify_result": 0,
        "time_namelookup": 0.015,
        "time_connect": 0.045,
        "time_appconnect": 0.120,
        "num_redirects": 0,
        "url_effective": "https://httpbin.org/get"
    }
}
```
