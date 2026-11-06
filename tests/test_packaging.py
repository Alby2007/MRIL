"""Packaging invariants — the local-first install contract.

Subprocess-level checks so they hold regardless of what this dev env
happens to have installed (e.g. LangChain present in the test venv must
not let `import mril` pull it in).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

OPTIONAL_DEPS = ("langchain", "langchain_core", "langgraph", "ollama",
                 "openai", "anthropic", "requests", "httpx")


def test_import_mril_pulls_no_optional_deps(tmp_path):
    """`import mril` must not import or require any optional dependency."""
    code = (
        "import sys, mril\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {OPTIONAL_DEPS!r})\n"
        "print('leaked:', bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # importing the package must not touch the filesystem either (no mril.db)
    assert list(tmp_path.iterdir()) == []


def test_adapter_importable_without_langchain(tmp_path):
    """mril.adapters.langchain degrades to a plain base when LC is absent."""
    code = textwrap.dedent(
        """
        import sys

        # sys.modules[name] = None marks a package as unimportable — the
        # reliable way to simulate "extra not installed" in-process.
        for name in ('langchain', 'langchain_core', 'langgraph'):
            sys.modules[name] = None
        import mril.adapters.langchain as a
        assert a._Base is object, a._Base
        mw = a.MRILMiddleware.__new__(a.MRILMiddleware)
        print('degraded import ok')
        """
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "degraded import ok" in proc.stdout


@pytest.mark.skipif(
    subprocess.run(
        [sys.executable, "-c", "import langchain.agents"],
        capture_output=True,
    ).returncode != 0,
    reason="langchain extra not installed",
)
def test_adapter_subclasses_agent_middleware_when_installed():
    """With the extra installed, hooks are discoverable by create_agent."""
    from langchain.agents.middleware import AgentMiddleware

    from mril.adapters.langchain import MRILMiddleware

    assert issubclass(MRILMiddleware, AgentMiddleware)
