from aria.core.runtime import TAVILY_API_KEY

class AriaWebSearchMixin:
    def _search_tavily(self, query: str) -> str:
        try:
            import requests 
            res = requests.post("https://api.tavily.com/search", json={"api_key": TAVILY_API_KEY, "query": query, "include_answer": True}, timeout=10).json()
            contexts = [f"- {r['title']}: {r['content']}" for r in res.get("results", [])]
            return f"Jawaban Singkat: {res.get('answer', 'Tidak ada.')}\n\nSumber/Konteks:\n" + "\n".join(contexts)
        except Exception as e: return f"Error API Internet: {e}"

