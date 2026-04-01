"""
pipeline/uploader.py

Supabase Storage 업로드 + DB status 업데이트
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import Optional, Tuple

load_dotenv()

supabase: Client = create_client(
    os.getenv("SUPABASE_URL", ""),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
)


async def upload_to_supabase(
    video_path: str,
    audio_path: str,
    video_id: str,
) -> Tuple[str, str]:
    """
    완성 영상 + 나레이션 오디오를 Supabase Storage에 업로드

    Returns:
        (video_public_url, audio_public_url)
    """
    # 1. 영상 업로드
    video_file_name = f"composed/{video_id}.mp4"
    with open(video_path, "rb") as f:
        video_data = f.read()

    supabase.storage.from_("videos").upload(
        video_file_name,
        video_data,
        {"content-type": "video/mp4", "upsert": "true"},
    )
    video_url = supabase.storage.from_("videos").get_public_url(video_file_name)
    print(f"[Uploader] 영상 업로드 완료: {video_url}")

    # 2. 오디오 업로드
    audio_file_name = f"{video_id}.mp3"
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    supabase.storage.from_("audio").upload(
        audio_file_name,
        audio_data,
        {"content-type": "audio/mpeg", "upsert": "true"},
    )
    audio_url = supabase.storage.from_("audio").get_public_url(audio_file_name)
    print(f"[Uploader] 오디오 업로드 완료: {audio_url}")

    # 3. 임시 파일 삭제
    for path in [video_path, audio_path]:
        try:
            if os.path.exists(path):
                os.remove(path)
                print(f"[Uploader] 임시 파일 삭제: {path}")
        except Exception:
            pass

    return video_url, audio_url


async def update_video_db(
    video_id: str,
    status: str,
    extra: Optional[dict] = None,
):
    """
    Supabase DB videos 테이블 업데이트

    Args:
        video_id: 영상 ID
        status:   'generating' | 'ready' | 'failed'
        extra:    추가 업데이트 필드 (title, storage_url 등)
    """
    update_data = {"status": status}

    if extra:
        # None 값은 제외
        update_data.update({k: v for k, v in extra.items() if v is not None})

    result = supabase.table("videos") \
        .update(update_data) \
        .eq("id", video_id) \
        .execute()

    print(f"[DB] status={status} 업데이트 완료: video_id={video_id}")
    return result
