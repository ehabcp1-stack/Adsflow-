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


# --------------------------------------------------------------------------
# Recovering JSON from a reply that is not bare JSON
# --------------------------------------------------------------------------
def test_bare_json_passes_through_unchanged():
    from app.providers.adapters import _first_json_object

    assert _first_json_object('{"a": 1}') == '{"a": 1}'


def test_a_fenced_block_is_unwrapped():
    from app.providers.adapters import _first_json_object

    assert _first_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_a_sentence_before_the_object_is_dropped():
    from app.providers.adapters import _first_json_object

    assert _first_json_object('Here you go:\n{"a": 1}') == '{"a": 1}'


def test_nested_braces_keep_the_outermost_object():
    from app.providers.adapters import _first_json_object

    assert _first_json_object('{"a": {"b": 2}}') == '{"a": {"b": 2}}'


def test_a_reply_with_no_object_is_returned_as_is():
    """The caller must still see a real parse error, not an empty string."""
    from app.providers.adapters import _first_json_object

    assert _first_json_object("I cannot do that") == "I cannot do that"
