"""Official plugins for the curl execution orchestrator."""

from curl import CurlPlugin, CurlRequest


class WebProxyPlugin(CurlPlugin):
    """A transport-layer plugin that routes requests through a web proxy.
    
    This plugin intercepts outgoing requests and prepends a specific proxy
    URL to the destination URL. It also normalizes the yielded results back to 
    their original URL state so it operates fully transparently to the end-user.
    """

    def __init__(self, proxy_prefix: str = "https://proxy.esperoj.eu.org/"):
        """Initializes the proxy plugin.
        
        Args:
            proxy_prefix: The proxy endpoint to prepend to all target URLs.
        """
        # Ensure the prefix always ends with a slash for clean concatenation
        self.proxy_prefix = proxy_prefix if proxy_prefix.endswith("/") else f"{proxy_prefix}/"

    def modify_request(self, request: CurlRequest) -> CurlRequest:
        """Intercepts the outgoing request to inject the proxy prefix."""
        # Prevent double-prefixing if a user passes the same request twice
        if not request.url.startswith(self.proxy_prefix):
            request.url = f"{self.proxy_prefix}{request.url}"
            
        return request

    def modify_result(self, result: dict[str, object]) -> dict[str, object]:
        """Intercepts the completed result to strip the proxy prefix."""
        # Restore the original URL in the result dictionary so the caller 
        # doesn't have to deal with the prefixed version manually.
        if "url" in result and isinstance(result["url"], str):
            if result["url"].startswith(self.proxy_prefix):
                result["url"] = result["url"][len(self.proxy_prefix):]
                
        return result
