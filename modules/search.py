import wikipedia as wiki_lib

def search_wikipedia(query):
    try:
        result = wiki_lib.summary(query, sentences=2)
        return f"According to Wikipedia: {result}"
    except wiki_lib.exceptions.DisambiguationError:
        return f"I found multiple results for '{query}'. Could you be more specific?"
    except wiki_lib.exceptions.PageError:
        return f"I couldn't find anything about '{query}' on Wikipedia."
