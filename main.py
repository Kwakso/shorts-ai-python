from fastapi import FastAPI, BackgroundTasks, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
os.environ['PYTHONUNBUFFERED'] = '1'

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"], 
)

RAILWAY_API_KEY = os.getenv("RAILWAY_API_KEY", "")

class GenerateRequest(BaseModel):
    video_id: str
    topic: str
    style: str = "documentary"
    language: str = "ko"

@app.get("/health")
def health():
    return {"status": "ok", "server": "ShortsAI Python Pipeline"}

@app.post("/generate")
async def generate(
    req: GenerateRequest,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None),
):
    if RAILWAY_API_KEY and x_api_key != RAILWAY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    background_tasks.add_task(run_pipeline, req)
    return {"success": True, "message": "파이프라인 시작", "video_id": req.video_id}

async def run_pipeline(req: GenerateRequest):
    from pipeline.gemini import generate_script
    from pipeline.tts import generate_tts
    from pipeline.pexels import search_videos
    from pipeline.composer import compose_video
    from pipeline.uploader import upload_to_supabase, update_video_db

    video_id = req.video_id
    try:
        print(f"[Pipeline] 시작: {req.topic}")
        await update_video_db(video_id, "generating")

        # 1. Gemini 스크립트
        script = await generate_script(req.topic, req.style, req.language)
        await update_video_db(video_id, "generating", {"title": script["title"]})
        print(f"[Pipeline] 스크립트 완료: {script['title']}")

        # 2. TTS
        audio_path = await generate_tts(script["script"], req.language, video_id)
        print(f"[Pipeline] TTS 완료")

        # 3. Pexels
        video_urls = await search_videos(script.get("searchKeywords", [req.topic]), 5)
        print(f"[Pipeline] Pexels {len(video_urls)}개 검색 완료")

        # 4. ffmpeg 합성
        output_path = await compose_video(video_id, video_urls, audio_path, script["script"])
        print(f"[Pipeline] 합성 완료")

        # 5. Supabase 업로드
        storage_url, audio_url = await upload_to_supabase(output_path, audio_path, video_id)

        # 완료
        await update_video_db(video_id, "ready", {
            "storage_url": storage_url,
            "audio_url": audio_url,
            "title": script["title"],
            "description": script["description"],
            "tags": script["tags"],
        })
        print(f"[Pipeline] 완료!")

    except Exception as e:
        print(f"[Pipeline] 오류: {e}")
        await update_video_db(video_id, "failed")