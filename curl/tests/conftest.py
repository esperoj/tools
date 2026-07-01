import pytest
from unittest.mock import patch
from pathlib import Path
from curl import CurlRequest


class MockStdout:
    """Mocks standard output stream returning character by character."""
    def __init__(self, text, process):
        self.text = text
        self.idx = 0
        self.process = process

    def read(self, n=1):
        if self.idx < len(self.text):
            char = self.text[self.idx]
            self.idx += 1
            return char
        self.process.is_finished = True
        return ""


class MockProcess:
    """Mocks the subprocess.Popen object returning streamable output."""
    def __init__(self, stdout_text=""):
        self.stdout = MockStdout(stdout_text, self)
        self.returncode = 0
        self.is_finished = False

    def poll(self):
        return 0 if self.is_finished else None

    def wait(self):
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def mock_popen():
    """Fixture that intercepts subprocess.Popen and allows providing mock stdout text."""
    patchers = []

    def _factory(stdout_text=""):
        patcher = patch("subprocess.Popen", return_value=MockProcess(stdout_text))
        patchers.append(patcher)
        return patcher.start()

    yield _factory

    for p in patchers:
        p.stop()


@pytest.fixture
def sample_request(tmp_path):
    """Fixture returning a basic CurlRequest."""
    output = tmp_path / "out.bin"
    return CurlRequest(url="https://example.com", output_path=output)
