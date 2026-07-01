from curl import CurlRequest
from proxy import WebProxyPlugin

def test_web_proxy_plugin_init():
    # Ensures trailing slash is added natively
    plugin1 = WebProxyPlugin("https://myproxy.com")
    assert plugin1.proxy_prefix == "https://myproxy.com/"
    
    plugin2 = WebProxyPlugin("https://myproxy.com/")
    assert plugin2.proxy_prefix == "https://myproxy.com/"

def test_web_proxy_plugin_modify_request():
    plugin = WebProxyPlugin("https://proxy.net/")
    req = CurlRequest(url="https://target.com/api", output_path="out.bin")
    
    # Should prepend the proxy address
    modified = plugin.modify_request(req)
    assert modified.url == "https://proxy.net/https://target.com/api"
    
    # Should not double-prepend if passed through again
    modified_again = plugin.modify_request(modified)
    assert modified_again.url == "https://proxy.net/https://target.com/api"

def test_web_proxy_plugin_modify_result():
    plugin = WebProxyPlugin("https://proxy.net/")
    
    # Should strip the proxy domain from the result representation
    result = {"url": "https://proxy.net/https://target.com/api", "status": 200}
    modified_result = plugin.modify_result(result)
    assert modified_result["url"] == "https://target.com/api"
    
    # Should safely ignore URLs that don't have the proxy prefix
    clean_result = {"url": "https://other.com/api"}
    modified_clean = plugin.modify_result(clean_result)
    assert modified_clean["url"] == "https://other.com/api"
    
    # Should safely ignore results that are missing the URL key
    no_url_result = {"status": 500}
    modified_no_url = plugin.modify_result(no_url_result)
    assert "url" not in modified_no_url
