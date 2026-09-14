"""Every selectable model must have an adapter that can actually run it.

The catalog listed claude-sonnet-5 and claude-opus-5 as selectable for weeks
while `registry._REGISTRY["llm"]` had no "anthropic" entry at all. The router
chose ("anthropic", "claude-sonnet-5"), the registry found nothing under that
name and returned the Mock, and every script was written by a template — with
a paid key configured and the settings screen reporting `production`. Nothing
failed, nothing logged, and the output looked plausible, which is the only
reason it survived.
"""
from __future__ import annotations

import pytest

from app.providers import catalog, registry


def _selectable_providers(kind: str) -> set[str]:
    return {
        spec.provider_id
        for spec in catalog.specs_for_kind(kind)
        if spec.selectable and spec.provider_id != "mock"
    }


@pytest.mark.parametrize("kind", sorted(registry._REGISTRY.keys()))
def test_every_selectable_provider_has_an_adapter(kind: str):
    registered = set(registry._REGISTRY[kind].keys())
    missing = sorted(_selectable_providers(kind) - registered)
    assert not missing, (
        f"{kind}: the catalog offers these providers but no adapter implements "
        f"them, so the router will pick one and silently get the Mock: {missing}"
    )


@pytest.mark.parametrize("kind", sorted(registry._REGISTRY.keys()))
def test_no_adapter_is_registered_without_a_catalog_entry(kind: str):
    """The reverse: an adapter nothing can route to is dead weight.

    Not a failure the way the other direction is, but it means a provider was
    wired up and then never made selectable — worth knowing about.
    """
    registered = {name for name in registry._REGISTRY[kind] if name != "mock"}
    known = {spec.provider_id for spec in catalog.specs_for_kind(kind)}
    orphans = sorted(registered - known)
    assert not orphans, f"{kind}: adapters with no catalog entry: {orphans}"


def test_anthropic_is_the_writer_for_arabic():
    """Pinned by name: Claude is what writes the Iraqi-dialect scripts.

    If this adapter disappears again the scripts fall back to a template, and
    the failure is invisible in every screen the product has.
    """
    assert "anthropic" in registry._REGISTRY["llm"]
    adapter = registry._REGISTRY["llm"]["anthropic"]
    assert adapter.key_setting == "ANTHROPIC_API_KEY"
    assert {"claude-sonnet-5", "claude-opus-5"} <= {
        spec.model_id for spec in catalog.specs_for_kind("llm") if spec.provider_id == "anthropic"
    }
