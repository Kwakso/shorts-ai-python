"""
pipeline/composer.py
====================
Pexels 스톡 영상 + 나레이션 + Alex Hormozi 스타일 자막 합성

자막 스타일:
- 굵은 폰트 + 흰색 + 검정 외곽선
- 하단 중앙 고정
- 나눔고딕 한국어 폰트
"""

import os
import re
import asyncio
import httpx
import subprocess
from typing import List, Optional

FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
FONT_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def get_font_path() -> str:
    return FONT_PATH if os.path.exists(FONT_PATH) else FONT_FALLBACK


def get_duration(file_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         file_path],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def generate_srt(script: str, audio_duration: float, output_path: str):
    sentences = re.split(r'(?<=[.!?])\s+|(?<=[,])\s+', script.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        sentences = [script.strip()]

    duration_per = audio_duration / len(sentences)

    def to_srt_time(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(output_path, "w", encoding="utf-8") as f:
        current = 0.0
        for i, sentence in enumerate(sentences, 1):
            start = current
            end = current + duration_per
            f.write(f"{i}\n")
            f.write(f"{to_srt_time(start)} --> {to_srt_time(end)}\n")
            f.write(f"{sentence}\n\n")
            current = end

    print(f"[SRT] 생성 완료: {len(sentences)}개 문장")


async def download_videos(video_urls: List[str], video_id: str) -> List[str]:
    os.makedirs("tmp", exist_ok=True)
    paths = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for i, url in enumerate(video_urls[:5]):
            try:
                print(f"[Download] 영상 {i+1} 다운로드 중...")
                res = await client.get(url)
                path = f"tmp/{video_id}_clip{i}.mp4"
                with open(path, "wb") as f:
                    f.write(res.content)
                paths.append(path)
                print(f"[Download] 완료: {len(res.content)//1024}KB")
            except Exception as e:
                print(f"[Download] 실패: {e}")
    return paths


async def compose_video(
    video_id: str,
    video_urls: List[str],
    audio_path: str,
    script: Optional[str] = None,
    output_dir: str = "output",
) -> str:
    os.makedirs("tmp", exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 1. 나레이션 길이
    audio_duration = get_duration(audio_path)
    print(f"[Compose] 나레이션: {audio_duration:.2f}초")
    if audio_duration < 1:
        raise Exception(f"나레이션 파일 오류: {audio_path}")

    # 2. SRT 자막 생성
    srt_path = None
    if script:
        srt_path = f"tmp/{video_id}.srt"
        generate_srt(script, audio_duration, srt_path)

    # 3. 영상 다운로드
    video_paths = await download_videos(video_urls, video_id)
    if not video_paths:
        raise Exception("다운로드된 영상 없음")

    # 4. 9:16 세로형 변환
    processed_clips = []
    for i, path in enumerate(video_paths):
        out = f"tmp/{video_id}_proc{i}.mp4"
        result = subprocess.run([
            "ffmpeg", "-y", "-i", path,
            "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an", "-r", "30",
            out,
        ], capture_output=True)
        if result.returncode == 0:
            processed_clips.append(out)
            print(f"[Compose] 클립 {i+1} 전처리 완료")

    if not processed_clips:
        raise Exception("전처리된 클립 없음")

    # 5. 클립 연결 + Loop
    concat_path = f"tmp/{video_id}_concat.mp4"
    _concat_and_loop(processed_clips, audio_duration, concat_path, video_id)

    # 6. 나레이션 + 자막 합성
    output_path = f"{output_dir}/{video_id}.mp4"
    _add_audio_and_subtitle(concat_path, audio_path, srt_path, output_path)

    # 7. 임시 파일 정리
    _cleanup(video_paths + processed_clips + [concat_path])
    if srt_path and os.path.exists(srt_path):
        os.remove(srt_path)

    print(f"[Compose] 완성: {output_path}")
    return output_path


def _concat_and_loop(clip_paths, target_duration, output_path, video_id):
    repeated = []
    current = 0.0
    cycle = 0
    while current < target_duration and cycle < 30:
        for path in clip_paths:
            if current >= target_duration:
                break
            repeated.append(path)
            current += get_duration(path)
        cycle += 1

    list_path = f"tmp/{video_id}_list.txt"
    with open(list_path, "w") as f:
        for path in repeated:
            abs_path = os.path.abspath(path).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-t", str(target_duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-r", "30",
        output_path,
    ], capture_output=True)

    os.remove(list_path)
    print(f"[Concat] 완료 ({len(repeated)}개 클립)")


def _add_audio_and_subtitle(video_path, audio_path, srt_path, output_path):
    font_path = get_font_path()
    font_dir = os.path.dirname(font_path)

    if srt_path and os.path.exists(srt_path):
        abs_srt = os.path.abspath(srt_path).replace("\\", "/")
        # 콜론 이스케이프 (Linux)
        abs_srt_escaped = abs_srt.replace(":", "\\:")

        # Alex Hormozi 스타일
        subtitle_filter = (
            f"subtitles='{abs_srt_escaped}'"
            f":fontsdir='{font_dir}'"
            ":force_style='"
            "FontName=NanumGothicBold,"
            "FontSize=24,"
            "Bold=1,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BackColour=&H80000000,"
            "Outline=3,"
            "Shadow=1,"
            "Alignment=2,"
            "MarginV=100,"
            "MarginL=20,"
            "MarginR=20"
            "'"
        )
        vf = subtitle_filter
    else:
        vf = None

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path, "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-map", "0:v:0", "-map", "1:a:0",
    ]
    if vf:
        cmd += ["-vf", vf]
    cmd.append(output_path)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ffmpeg 오류] {result.stderr[-500:]}")
        raise Exception("ffmpeg 합성 실패")

    print(f"[Audio+Subtitle] 완료: {os.path.getsize(output_path)//1024}KB")


def _cleanup(paths):
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass