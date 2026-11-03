"""Verify the optional enabled adapter dependencies without starting services."""

def test_enabled_adapter_dependencies_import_without_services():
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from jsonschema import Draft202012Validator
    assert Client and streamable_http_client and Draft202012Validator and httpx2.AsyncClient