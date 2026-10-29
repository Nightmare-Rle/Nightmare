import requests
from bs4 import BeautifulSoup

def google_search(query):
    try:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        results = []

        for g in soup.find_all("div", class_="g")[:5]:
            link_tag = g.find("a")
            title_tag = g.find("h3")
            snippet_tag = g.find("div", {"data-sncf": "1"}) or g.find("span", class_="aCOpRe") or g.find("span", style_="display:-webkit-box")

            title = title_tag.get_text() if title_tag else ""
            link = link_tag.get("href") if link_tag else ""

            snippet = ""
            for span in g.find_all("span"):
                t = span.get_text().strip()
                if len(t) > 30:
                    snippet = t
                    break

            if title and link:
                results.append({"title": title, "link": link, "snippet": snippet})

        return results

    except Exception as e:
        return []

def format_search_context(results):
    if not results:
        return "No search results found."
    context_parts = []
    for r in results[:3]:
        ctx = f"Title: {r['title']}\nURL: {r['link']}"
        if r['snippet']:
            ctx += f"\nSummary: {r['snippet'][:300]}"
        context_parts.append(ctx)
    return "\n---\n".join(context_parts)

def search_and_summarize(query):
    results = google_search(query)
    return results, format_search_context(results)
