import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.core.budget import remaining_timeout, reserve_external_call
from app.core.privacy import public_search_query
from app.core.observability import span, trace_content, trace_details


def search_official_web(query, domains):
    query = public_search_query(query)
    settings = get_settings()
    provider = settings.web_search_provider
    if provider == "brave":
        key = settings.brave_api_key.get_secret_value()
        # Respect Brave's limits before sending a rewritten query.
        query = " ".join(query.split()[:75])[:600].strip()
        url = "https://api.search.brave.com/res/v1/llm/context?" + urlencode({
            "q": query, "country": "IN", "maximum_number_of_urls": 50,
            "maximum_number_of_tokens": 4096})
        request = Request(url, headers={"X-Subscription-Token": key, "Accept": "application/json"})
    else:
        key = settings.tavily_api_key.get_secret_value()
        request = Request("https://api.tavily.com/search", data=json.dumps({
            "query": query, "max_results": 5, "include_domains": list(domains),
            "include_answer": False, "search_depth": "basic"}).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    if not key or not query:
        raise ValueError("Search credentials and query are required")
    for attempt in range(settings.max_retries + 1):
        reserve_external_call("web")
        try:
            with span("web_provider_attempt", inputs={"query": trace_content(query)}) as trace:
                trace.update(provider=provider, attempt=attempt + 1)
                with urlopen(request, timeout=remaining_timeout()) as response:
                    data = json.load(response)
            break
        except (TimeoutError, URLError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == settings.max_retries:
                raise
            with span("web_retry_delay", inputs={"seconds": attempt + 1}):
                time.sleep(attempt + 1)
    if provider == "brave":
        items = [{"url": item.get("url", ""), "title": item.get("title", ""),
                  "content": "\n".join(item.get("snippets", []))}
                 for item in data.get("grounding", {}).get("generic", [])]
    else:
        items = data.get("results", [])
    results = []
    for item in items:
        parsed = urlparse(item.get("url", ""))
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "https" and not parsed.username and any(host == d or host.endswith("." + d) for d in domains):
            results.append(item)
    selected = results[:5]
    sources = [urlparse(item["url"]) for item in selected]
    trace_details(provider=provider, method="web", query=trace_content(query),
                  rejected_source_count=len(items) - len(results),
                  selected_sources=[{"host": source.hostname, "path": trace_content(source.path)}
                                    for source in sources])
    return {"results": selected}
