from fastapi import FastAPI, BackgroundTasks, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import sys

# 로그 버퍼링 비활성화
sys.stdout.reconfigure(line_buffering=True)

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
    from pipeline.gemini import generate_script, get_full_script, get_search_keywords
    from pipeline.tts import generate_tts
    from pipeline.pexels import search_videos
    from pipeline.composer import compose_video
    from pipeline.uploader import upload_to_supabase, update_video_db

    video_id = req.video_id

    try:
        print(f"[Pipeline] ===== 시작: {req.topic} =====", flush=True)
        await update_video_db(video_id, "generating")

        # ── STEP 1: Gemini → scenes 배열 생성 ──────────────
        print(f"[Pipeline] STEP 1: Gemini 스크립트 생성 중...", flush=True)
        script = await generate_script(req.topic, req.style, req.language)

        scenes = script.get("scenes", [])
        full_script = get_full_script(script)
        keywords = get_search_keywords(script)

        print(f"[Pipeline] STEP 1 완료: {script['title']}", flush=True)
        print(f"[Pipeline] scenes: {len(scenes)}개, 전체: {len(full_script)}자", flush=True)
        print(f"[Pipeline] 키워드: {keywords}", flush=True)

        await update_video_db(video_id, "generating", {"title": script["title"]})

        # ── STEP 2: TTS → 전체 스크립트로 나레이션 생성 ──
        print(f"[Pipeline] STEP 2: TTS 생성 중...", flush=True)
        audio_path = await generate_tts(full_script, req.language, video_id)
        print(f"[Pipeline] STEP 2 완료: {audio_path}", flush=True)

        # ── STEP 3: Pexels → scene별 키워드로 영상 검색 ──
        print(f"[Pipeline] STEP 3: Pexels 영상 검색 중...", flush=True)
        video_urls = await search_videos(keywords, count=len(scenes))
        print(f"[Pipeline] STEP 3 완료: {len(video_urls)}개 영상", flush=True)

        # ── STEP 4: ffmpeg 합성 ────────────────────────────
        print(f"[Pipeline] STEP 4: ffmpeg 합성 중...", flush=True)
        output_path = await compose_video(
            video_id=video_id,
            video_urls=video_urls,
            audio_path=audio_path,
            script=full_script,
        )
        print(f"[Pipeline] STEP 4 완료: {output_path}", flush=True)

        # ── STEP 5: Supabase 업로드 ───────────────────────
        print(f"[Pipeline] STEP 5: Supabase 업로드 중...", flush=True)
        storage_url, audio_url = await upload_to_supabase(output_path, audio_path, video_id)
        print(f"[Pipeline] STEP 5 완료: {storage_url}", flush=True)

        # ── 완료 ──────────────────────────────────────────
        await update_video_db(video_id, "ready", {
            "storage_url": storage_url,
            "audio_url": audio_url,
            "title": script["title"],
            "description": script["description"],
            "tags": script["tags"],
        })

        print(f"[Pipeline] ===== 완료! video_id={video_id} =====", flush=True)

    except Exception as e:
        import traceback
        print(f"[Pipeline] 오류 발생: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        await update_video_db(video_id, "failed")