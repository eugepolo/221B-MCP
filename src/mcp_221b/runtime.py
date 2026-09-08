"""Per-server tool instances sharing one managed HTTP client."""

from mcp_221b.network import Network
from mcp_221b.tool_handlers.inspect_page import InspectPage
from mcp_221b.tool_handlers.lookup_domain import LookupDomain
from mcp_221b.tool_handlers.search_archives import SearchArchives
from mcp_221b.tool_handlers.search_username import SearchUsername
from mcp_221b.tool_handlers.search_web import SearchWeb


class ToolHandlers:
    def __init__(self, network: Network):
        self.web = SearchWeb(network)
        self.search_web = self.web.search_web
        self.search_username = SearchUsername(network).search_username
        self.inspect_page = InspectPage(network).inspect_page
        self.lookup_domain = LookupDomain(network).lookup_domain
        self.search_archives = SearchArchives(network).search_archives
