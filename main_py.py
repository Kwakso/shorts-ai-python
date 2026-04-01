"""
main.py — Railway Python 서버 (FastAPI)

역할:
- Next.js에서 /generate POST 요청 수신
- 백그라운드에서 파이프라인 실행 (Gemini → TTS → Pexels → ffmpeg → Supabase)
- 완료 시 Supabase DB videos.status → 'ready' 업데이트
"""

import os
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

from pipeline.gemini import generate_script
from pipeline.tts import generate_tts
from pipeline.pexels import search_videos
from pipeline.composer import compose_video
from pipeline.uploader import upload_to_supabase, update_video_db

load_dotenv()

app = FastAPI(title="ShortsAI Python Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RAILWAY_API_KEY = os.getenv("RAILWAY_API_KEY", "")


# ─── 요청 스키마 ──────────────────────────────────────────────

class GenerateRequest(BaseModel):
    video_id: str
    topic: str
    style: str = "documentary"
    language: str = "ko"


# ─── 헬스체크 ─────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "server": "ShortsAI Python Pipeline"}


# ─── 영상 생성 엔드포인트 ─────────────────────────────────────

@app.post("/generate")
async def generate(
    req: GenerateRequest,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None),
):
    # API 키 검증
    if RAILWAY_API_KEY and x_api_key != RAILWAY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 백그라운드 파이프라인 실행 (즉시 응답 반환)
    background_tasks.add_task(run_pipeline, req)

    return {
        "success": True,
        "message": "파이프라인 시작",
        "video_id": req.video_id,
    }


# ─── 메인 파이프라인 ──────────────────────────────────────────

async def run_pipeline(req: GenerateRequest):
    video_id = req.video_id

    try:
        print(f"\n{'='*50}")
        print(f"[Pipeline] 시작: {req.topic}")
        print(f"[Pipeline] video_id: {video_id}")
        print(f"{'='*50}")

        # ── STEP 1: Gemini 스크립트 + 키워드 생성 ────────────
        print("[Pipeline] STEP 1: Gemini 스크립트 생성 중...")
        await update_video_db(video_id, "generating", {"title": None})

        script = await generate_script(req.topic, req.style, req.language)

        await update_video_db(video_id, "generating", {
            "title": script["title"],
            "description": script["description"],
            "script": script["script"],
            "video_prompt": script.get("videoPrompt", ""),
            "tags": script["tags"],
        })
        print(f"[Pipeline] STEP 1 완료: {script['title']}")
        print(f"[Pipeline] 검색 키워드: {script.get('searchKeywords', [])}")

        # ── STEP 2: Google TTS 나레이션 생성 ─────────────────
        print("[Pipeline] STEP 2: TTS 나레이션 생성 중...")
        audio_path = await generate_tts(
            text=script["script"],
            language=req.language,
            video_id=video_id,
        )
        print(f"[Pipeline] STEP 2 완료: {audio_path}")

        # ── STEP 3: Pexels 스톡 영상 검색 ────────────────────
        print("[Pipeline] STEP 3: Pexels 스톡 영상 검색 중...")
        keywords = script.get("searchKeywords", [req.topic, req.style])
        video_urls = await search_videos(keywords, count=5)

        if not video_urls:
            raise Exception("Pexels에서 영상을 찾을 수 없습니다.")

        print(f"[Pipeline] STEP 3 완료: {len(video_urls)}개 영상")

        # ── STEP 4: ffmpeg 합성 (영상 + 음성 + 자막) ─────────
        print("[Pipeline] STEP 4: ffmpeg 합성 중...")
        output_path = await compose_video(
            video_id=video_id,
            video_urls=video_urls,
            audio_path=audio_path,
            script=script["script"],
        )
        print(f"[Pipeline] STEP 4 완료: {output_path}")

        # ── STEP 5: Supabase Storage 업로드 ──────────────────
        print("[Pipeline] STEP 5: Supabase 업로드 중...")
        storage_url, audio_url = await upload_to_supabase(
            video_path=output_path,
            audio_path=audio_path,
            video_id=video_id,
        )
        print(f"[Pipeline] STEP 5 완료: {storage_url}")

        # ── 완료: DB status → ready ───────────────────────────
        await update_video_db(video_id, "ready", {
            "storage_url": storage_url,
            "audio_url": audio_url,
        })

        print(f"\n{'='*50}")
        print(f"[Pipeline] 완료! video_id: {video_id}")
        print(f"[Pipeline] 영상 URL: {storage_url}")
        print(f"{'='*50}\n")

    except Exception as e:
        print(f"\n[Pipeline] 오류 발생: {e}")
        # 실패 시 status → failed
        await update_video_db(video_id, "failed", {
            "error_message": str(e)[:500],
        })
