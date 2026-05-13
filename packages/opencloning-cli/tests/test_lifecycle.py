"""Unit tests for stub lifecycle helpers."""

from __future__ import annotations

from opencloning_cli.lifecycle import _STUB_CREATED_AT, _replace_created_at_in_json


def test_replace_created_at_nested_and_lists():
    original = {
        'items': [
            {'id': 1, 'created_at': '2026-01-01T00:00:00Z', 'nested': {'created_at': 'x'}},
            {'created_at': None},
        ],
        'created_at': 'old',
        'keep': 42,
    }
    out = _replace_created_at_in_json(original)

    assert out['created_at'] == _STUB_CREATED_AT
    assert out['keep'] == 42
    assert out['items'][0]['id'] == 1
    assert out['items'][0]['created_at'] == _STUB_CREATED_AT
    assert out['items'][0]['nested']['created_at'] == _STUB_CREATED_AT
    assert out['items'][1]['created_at'] == _STUB_CREATED_AT
    # input must be unchanged (no shared dict mutation)
    assert original['created_at'] == 'old'


def test_replace_created_at_scalars_unchanged():
    assert _replace_created_at_in_json('text') == 'text'
    assert _replace_created_at_in_json(3) == 3
    assert _replace_created_at_in_json(None) is None
