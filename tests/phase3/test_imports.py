"""Smoke test: verify all Phase 3 exports are importable from the top-level package."""


def test_all_phase3_imports():
    from declaw import (
        ALL_TRAFFIC,
        AsyncSandbox,
        AsyncSandboxPaginator,
        AsyncTemplate,
        Sandbox,
        SandboxPaginator,
        Template,
        TemplateBase,
    )

    assert Sandbox is not None
    assert AsyncSandbox is not None
    assert Template is not None
    assert AsyncTemplate is not None
    assert TemplateBase is not None
    assert SandboxPaginator is not None
    assert AsyncSandboxPaginator is not None
    assert ALL_TRAFFIC == "0.0.0.0/0"
