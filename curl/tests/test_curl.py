import json
import pytest
from pathlib import Path
from unittest.mock import patch

from curl import (
    Response, 
    CurlRequest, 
    CurlPlugin, 
    ParallelCurlRunner,
    request, get, post, put, patch as http_patch, delete
)


# ==============================================================================
# Response Tests
# ==============================================================================

def test_response_properties():
    content = b'{"success": true}'
    metrics = {"status": 200, "url": "https://example.com"}
    resp = Response(200, "https://example.com", content, metrics)
    
    assert resp.status_code == 200
    assert resp.url == "https://example.com"
    assert resp.text == '{"success": true}'
    assert resp.json() == {"success": true}
    assert resp.metrics == metrics
    assert repr(resp) == "<Response [200]>"

def test_response_text_fallback_encoding():
    # Test invalid utf-8 byte sequence
    content = b'\xff\xfe\xfd'
    resp = Response(200, "http://test", content, {})
    # Should safely replace without crashing
    assert "" in resp.text 

def test_response_raise_for_status():
    resp_success = Response(200, "http://test", b'', {})
    resp_success.raise_for_status()  # Should not raise

    resp_error = Response(404, "http://test", b'', {})
    with pytest.raises(Exception, match="HTTP Error 404 for url: http://test"):
        resp_error.raise_for_status()


# ==============================================================================
# Base Plugin Tests
# ==============================================================================

def test_curl_plugin_base(sample_request):
    plugin = CurlPlugin()
    assert plugin.modify_request(sample_request) is sample_request
    
    res = {"status": 200}
    assert plugin.modify_result(res) is res


# ==============================================================================
# ParallelCurlRunner Engine Tests
# ==============================================================================

def test_runner_empty_execution():
    runner = ParallelCurlRunner()
    events = list(runner.execute([]))
    assert events == []

def test_build_config_file(tmp_path):
    runner = ParallelCurlRunner(
        max_parallel=2, 
        global_options={"location": True, "fail": False, "timeout": 30, "user-agent": 'My"App"\\1'}
    )
    
    req1 = CurlRequest("http://a.com", tmp_path/"1", options={"max-time": 5})
    req2 = CurlRequest("http://b.com", tmp_path/"2", method="POST", data=b"raw bytes")
    req3 = CurlRequest("http://c.com", tmp_path/"3", method="PUT", data="text data", headers={"X-Header": "v\\a\"l"})
    req4 = CurlRequest("http://d.com", tmp_path/"4", method="PATCH", json_data={"foo": "bar"})
    
    config_file = tmp_path / "config.txt"
    runner._build_config_file(config_file, tmp_path, [req1, req2, req3, req4])
    
    content = config_file.read_text(encoding="utf-8")
    
    # Check globals
    assert "parallel-max = 2" in content
    assert "location\n" in content
    assert "no-fail\n" in content
    assert "timeout = 30\n" in content
    assert 'user-agent = "My\\"App\\"\\\\1"\n' in content
    
    # Check requests
    assert 'url = "http://a.com"' in content
    assert 'url = "http://b.com"' in content
    assert 'request = "POST"' in content
    assert 'request = "PUT"' in content
    assert 'request = "PATCH"' in content
    
    # Check options formatting and header escaping
    assert "max-time = 5\n" in content
    assert 'header = "X-Header: v\\\\a\\"l"' in content
    
    # Check payload files generation
    payload_files = list(tmp_path.glob("payload_*"))
    assert len(payload_files) == 3  # req2, req3, req4 have payloads
    
    json_payload = next(f for f in payload_files if f.suffix == ".json")
    assert json.loads(json_payload.read_text()) == {"foo": "bar"}

def test_parse_parallel_progress():
    runner = ParallelCurlRunner()
    
    # Standard valid string
    line = "DL: 100M UL: 20M XFR: 5/10 ETA: 00:01:00"
    res = runner._parse_parallel_progress(line)
    assert res == {
        "download_speed": "100M",
        "upload_speed": "20M",
        "completed_files": 5,
        "total_files": 10,
        "eta": "00:01:00"
    }
    
    # Handle missing spaces or alternative outputs
    line_alt = "DL:100M UL:0 XFR:5/10 ETA:--:--:--"
    res_alt = runner._parse_parallel_progress(line_alt)
    assert res_alt["download_speed"] == "100M"
    assert res_alt["eta"] == "--:--:--"
    
    # Exception handling/malformed inputs
    res_err = runner._parse_parallel_progress("XFR: a/b")
    assert res_err is None  # Value error captured and safely ignored

def test_process_result():
    runner = ParallelCurlRunner()
    
    valid_json = '{"url_effective": "http://test", "http_code": 200, "size_download": 1024}'
    res = runner._process_result(valid_json)
    
    assert res["event"] == "result"
    assert res["data"]["status"] == 200
    assert res["data"]["size_bytes"] == 1024
    assert res["data"]["url"] == "http://test"
    
    invalid_json = '{"url_effective": "http'
    assert runner._process_result(invalid_json) is None

def test_runner_execute_loop(mock_popen, sample_request):
    # Simulated curl output byte stream
    stream_output = (
        "DL: 10M XFR: 0/1 ETA: 00:10\r\n"
        '{"url_effective": "http://a.com", "http_code": 200}\n'
        '{"url_effective": "http://b.com", "http_code": 404}'  # Tests dangling buffer logic
    )
    mock_popen(stream_output)
    
    runner = ParallelCurlRunner()
    events = list(runner.execute([sample_request]))
    
    assert len(events) == 4
    assert events[0]["event"] == "init"
    
    assert events[1]["event"] == "progress"
    assert events[1]["data"]["download_speed"] == "10M"
    
    assert events[2]["event"] == "result"
    assert events[2]["data"]["status"] == 200
    
    assert events[3]["event"] == "result"
    assert events[3]["data"]["status"] == 404


# ==============================================================================
# Ergonomic API Tests
# ==============================================================================

@pytest.fixture
def mock_runner_execute():
    """Mocks ParallelCurlRunner.execute for Ergonomic API tests."""
    with patch("curl.ParallelCurlRunner.execute") as mock_exec:
        def side_effect(requests):
            # Create dummy payload file to simulate successful curl dump
            req = requests[0]
            Path(req.output_path).write_bytes(b"mock output")
            yield {"event": "init", "total": 1}
            yield {"event": "result", "data": {"status": 200, "url": req.url}}
        
        mock_exec.side_effect = side_effect
        yield mock_exec

def test_ergonomic_api_methods(mock_runner_execute):
    # GET
    resp = get("http://api.com", headers={"X": "1"})
    assert resp.status_code == 200
    assert resp.content == b"mock output"
    mock_runner_execute.assert_called_once()
    req_obj = mock_runner_execute.call_args[0][0][0]
    assert req_obj.method == "GET"
    assert req_obj.headers == {"X": "1"}
    
    mock_runner_execute.reset_mock()
    
    # POST
    post("http://api.com", json={"data": 123})
    req_obj = mock_runner_execute.call_args[0][0][0]
    assert req_obj.method == "POST"
    assert req_obj.json_data == {"data": 123}
    
    mock_runner_execute.reset_mock()

    # PUT
    put("http://api.com", data="raw string")
    req_obj = mock_runner_execute.call_args[0][0][0]
    assert req_obj.method == "PUT"
    assert req_obj.data == "raw string"

    mock_runner_execute.reset_mock()
    
    # PATCH
    http_patch("http://api.com")
    req_obj = mock_runner_execute.call_args[0][0][0]
    assert req_obj.method == "PATCH"
    
    mock_runner_execute.reset_mock()
    
    # DELETE
    delete("http://api.com")
    req_obj = mock_runner_execute.call_args[0][0][0]
    assert req_obj.method == "DELETE"

def test_ergonomic_api_no_output_file(mock_runner_execute):
    # Ensure it works even if the output file wasn't created by curl (e.g. 404 or connection drop)
    def side_effect(requests):
        yield {"event": "result", "data": {"status": 500, "url": "err"}}
    
    mock_runner_execute.side_effect = side_effect
    
    resp = request("GET", "http://err.com")
    assert resp.status_code == 500
    assert resp.content == b""
