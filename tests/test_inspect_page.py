from unittest.mock import AsyncMock

import httpx

from mcp_221b.tool_handlers.inspect_page import InspectPage


async def test_page_extraction_and_limits():
    network = AsyncMock()
    network.get.return_value = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "https://example.org/a"),
        text='<title>Profile</title><script>secret-script</script><a href="/b">Link</a>'
        "<p>hello@example.org</p>" + "<p>body</p>" * 6000,
    )
    result = await InspectPage(network).inspect_page("https://example.org/a")
    evidence = result.findings[0].evidence
    assert evidence["links"] == ["https://example.org/b"]
    assert evidence["emails"] == ["hello@example.org"]
    assert "secret-script" not in evidence["text"]
    assert evidence["text_truncated"]
