"""Phase 51 Stage 6 — the connection-free gate of the database-backed integration test.

Nothing here connects to a service. The gate is a pure function of an environment mapping, and the
ordering test runs a child pytest on a throwaway module that has no database at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests.integration import test_investment_alert_snapshot_path as gate_module

_CRED = "sentinel-credential-not-real"  # appears in URLs; must never appear in any result
_GOOD_URL = f"postgresql+psycopg://p51_test:{_CRED}@127.0.0.1:55432/p51_scratch"


def _env(**overrides: str | None) -> dict[str, str]:
    base: dict[str, str] = {
        "CFI_P51_DB_TEST_CONFIRM": "p51_scratch_test",
        "CFI_DATABASE_URL": _GOOD_URL,
    }
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def _failures(env: Mapping[str, str]) -> tuple[str, ...]:
    return gate_module.evaluate_gate(env).failures


def test_valid_configuration_passes() -> None:
    result = gate_module.evaluate_gate(_env())
    assert result.ok is True
    assert result.failures == ()


def test_new_isolated_port_is_allowed() -> None:
    url = f"postgresql+psycopg://p51_test:{_CRED}@127.0.0.1:55433/p51_scratch"
    assert gate_module.evaluate_gate(_env(CFI_DATABASE_URL=url)).ok is True


def test_localhost_is_also_allowed() -> None:
    url = f"postgresql+psycopg://p51_test:{_CRED}@localhost:55432/p51_scratch"
    assert gate_module.evaluate_gate(_env(CFI_DATABASE_URL=url)).ok is True


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_unset_or_blank_runtime_url_is_accepted(blank: str | None) -> None:
    assert gate_module.evaluate_gate(_env(CFI_DATABASE_URL_RUNTIME=blank)).ok is True


@pytest.mark.parametrize("host", ["db", "10.0.0.5", "example.com", "LOCALHOST", "127.0.0.2", "::1"])
def test_wrong_host_is_refused(host: str) -> None:
    shown = f"[{host}]" if ":" in host else host
    url = f"postgresql+psycopg://p51_test:{_CRED}@{shown}:55432/p51_scratch"
    assert gate_module.FAIL_HOST in _failures(_env(CFI_DATABASE_URL=url))


@pytest.mark.parametrize("port", ["5432", "5543"])
def test_wrong_port_is_refused(port: str) -> None:
    url = f"postgresql+psycopg://p51_test:{_CRED}@127.0.0.1:{port}/p51_scratch"
    assert _failures(_env(CFI_DATABASE_URL=url)) == (gate_module.FAIL_PORT,)


def test_missing_port_is_refused() -> None:
    url = f"postgresql+psycopg://p51_test:{_CRED}@127.0.0.1/p51_scratch"
    assert gate_module.FAIL_PORT in _failures(_env(CFI_DATABASE_URL=url))


@pytest.mark.parametrize(
    "name", ["cfi", "cfi_test", "p51_scratch_test", "p51_scratch2", "P51_SCRATCH"]
)
def test_wrong_database_is_refused(name: str) -> None:
    url = f"postgresql+psycopg://p51_test:{_CRED}@127.0.0.1:55432/{name}"
    assert gate_module.FAIL_DATABASE in _failures(_env(CFI_DATABASE_URL=url))


def test_missing_database_name_is_refused() -> None:
    url = f"postgresql+psycopg://p51_test:{_CRED}@127.0.0.1:55432"
    failures = _failures(_env(CFI_DATABASE_URL=url))
    assert gate_module.FAIL_DATABASE in failures
    assert gate_module.FAIL_DERIVED in failures


@pytest.mark.parametrize(
    "confirm", [None, "", "p51_scratch", "cfi_test", "P51_SCRATCH_TEST", " p51_scratch_test"]
)
def test_incorrect_confirmation_is_refused(confirm: str | None) -> None:
    assert _failures(_env(CFI_P51_DB_TEST_CONFIRM=confirm)) == (gate_module.FAIL_CONFIRM,)


@pytest.mark.parametrize(
    "raw",
    [
        "not a url",
        "postgresql+psycopg://",
        "://",
        "postgresql+psycopg://u:p@h:notaport/db",
        "x" * 50,
    ],
)
def test_malformed_url_is_refused_without_echoing_it(raw: str) -> None:
    result = gate_module.evaluate_gate(_env(CFI_DATABASE_URL=raw))
    assert result.ok is False
    assert raw not in repr(result)


def test_missing_url_is_refused() -> None:
    assert gate_module.FAIL_URL_MISSING in _failures(_env(CFI_DATABASE_URL=None))
    assert gate_module.FAIL_URL_MISSING in _failures(_env(CFI_DATABASE_URL=""))


def test_nonblank_runtime_url_is_refused() -> None:
    other = f"postgresql+psycopg://p51_test:{_CRED}@127.0.0.1:55432/p51_scratch"
    assert _failures(_env(CFI_DATABASE_URL_RUNTIME=other)) == (gate_module.FAIL_RUNTIME,)


@pytest.mark.parametrize(
    "query", ["host=db.internal", "port=5432", "dbname=cfi", "sslmode=require"]
)
def test_query_parameters_that_could_override_the_target_are_refused(query: str) -> None:
    url = f"{_GOOD_URL}?{query}"
    assert gate_module.FAIL_URL_QUERY in _failures(_env(CFI_DATABASE_URL=url))


def test_results_never_contain_the_credential_or_the_url() -> None:
    bad_envs = [
        _env(CFI_DATABASE_URL=_GOOD_URL.replace("55432", "5432")),
        _env(CFI_DATABASE_URL=_GOOD_URL.replace("127.0.0.1", "db")),
        _env(CFI_DATABASE_URL=f"{_GOOD_URL}?host=elsewhere"),
        _env(CFI_DATABASE_URL_RUNTIME=_GOOD_URL),
        _env(CFI_P51_DB_TEST_CONFIRM="wrong"),
    ]
    for env in bad_envs:
        text = repr(gate_module.evaluate_gate(env))
        assert _CRED not in text
        assert "postgresql" not in text
        assert "127.0.0.1" not in text


def test_the_gate_reads_only_the_mapping_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CFI_P51_DB_TEST_CONFIRM", "p51_scratch_test")
    monkeypatch.setenv("CFI_DATABASE_URL", _GOOD_URL)
    assert gate_module.evaluate_gate({}).ok is False


def test_the_module_constants_are_the_approved_target() -> None:
    assert gate_module.ALLOWED_HOSTS == ("127.0.0.1", "localhost")
    assert gate_module.EXPECTED_PORTS == (55432, 55433)
    assert gate_module.EXPECTED_DATABASE == "p51_scratch"
    assert gate_module.EXPECTED_TEST_DATABASE == "p51_scratch_test"


def test_the_gate_decision_is_a_module_level_skip_mark() -> None:
    marks = [m for m in gate_module.pytestmark if m.name == "skipif"]
    assert len(marks) == 2  # requires_services and the gate
    assert any(m.args == (not gate_module._GATE.ok,) for m in marks)


def test_a_skipif_mark_stops_a_session_fixture_from_ever_being_created(tmp_path: Path) -> None:
    """The ordering the gate relies on, shown on a throwaway project with no database: a session
    fixture that would 'drop a database' (here, write a file) is never created for a skipped test,
    and is created for a test that is not skipped (so the probe itself is sound)."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "import pathlib, pytest\n"
        "@pytest.fixture(scope='session')\n"
        "def destructive(tmp_path_factory):\n"
        "    pathlib.Path(__file__).with_name('CREATED.txt').write_text('x')\n"
        "    yield\n",
        encoding="utf-8",
    )
    (tmp_path / "test_skipped.py").write_text(
        "import pytest\n"
        "pytestmark = pytest.mark.skipif(True, reason='gate')\n"
        "def test_a(destructive):\n    pass\n",
        encoding="utf-8",
    )
    child_env = os.environ.copy()
    for name in (
        "CFI_DATABASE_URL",
        "CFI_REDIS_URL",
        "CFI_DATABASE_URL_RUNTIME",
        "CFI_P51_DB_TEST_CONFIRM",
    ):
        child_env.pop(name, None)
    base = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        "--rootdir",
        str(tmp_path),
    ]
    skipped = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [*base, str(tmp_path / "test_skipped.py")],
        capture_output=True,
        text=True,
        env=child_env,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert "1 skipped" in skipped.stdout, skipped.stdout
    assert not (tmp_path / "CREATED.txt").exists()

    (tmp_path / "test_run.py").write_text("def test_b(destructive):\n    pass\n", encoding="utf-8")
    ran = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [*base, str(tmp_path / "test_run.py")],
        capture_output=True,
        text=True,
        env=child_env,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert "1 passed" in ran.stdout, ran.stdout
    assert (tmp_path / "CREATED.txt").exists()
