import os
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()

sb = create_client(
    os.getenv("SUPABASE_URL", ""),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
)

async def upload_to_supabase(video_path: str, audio_path: str, video_id: str):
    # 영상 업로드
    with open(video_path, "rb") as f:
        sb.storage.from_("videos").upload(
            f"composed/{video_id}.mp4", f.read(),
            {"content-type": "video/mp4", "upsert": "true"}
        )
    video_url = sb.storage.from_("videos").get_public_url(f"composed/{video_id}.mp4")

    # 오디오 업로드
    with open(audio_path, "rb") as f:
        sb.storage.from_("audio").upload(
            f"{video_id}.mp3", f.read(),
            {"content-type": "audio/mpeg", "upsert": "true"}
        )
    audio_url = sb.storage.from_("audio").get_public_url(f"{video_id}.mp3")

    # 임시 파일 삭제
    for p in [video_path, audio_path]:
        if os.path.exists(p):
            os.remove(p)

    return video_url, audio_url

async def update_video_db(video_id: str, status: str, extra: dict = None):
    data = {"status": status}
    if extra:
        data.update({k: v for k, v in extra.items() if v is not None})
    sb.table("videos").update(data).eq("id", video_id).execute()
    print(f"[DB] {video_id} → status={status}")
