import os, httpx
from dotenv import load_dotenv
load_dotenv()

async def search_videos(keywords: list, count: int = 5) -> list:
    results = []
    async with httpx.AsyncClient() as client:
        for keyword in keywords:
            if len(results) >= count:
                break
            try:
                res = await client.get(
                    "https://api.pexels.com/videos/search",
                    params={"query": keyword, "per_page": 3, "orientation": "portrait"},
                    headers={"Authorization": os.getenv("PEXELS_API_KEY")},
                    timeout=10,
                )
                for video in res.json().get("videos", []):
                    if len(results) >= count:
                        break
                    url = _best_url(video["video_files"])
                    if url:
                        results.append(url)
            except Exception as e:
                print(f"[Pexels] 오류 ({keyword}): {e}")
    return results

def _best_url(files: list) -> str:
    for f in files:
        if f.get("quality") == "hd" and f.get("height", 0) > f.get("width", 0):
            return f["link"]
    for f in files:
        if f.get("quality") == "hd":
            return f["link"]
    return files[0]["link"] if files else None