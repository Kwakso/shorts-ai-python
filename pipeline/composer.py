"""
composer.py
===========
Pexels 스톡 영상 + 나레이션 오디오 + SRT 자막 합성 스크립트

기능:
- 여러 개의 스톡 영상을 배경으로 연결
- 나레이션 오디오 길이에 맞춰 영상 자르기/반복(Loop)
- SRT 자막 파일을 읽어서 영상 하단에 burn-in
- 최종 9:16 세로형 MP4 출력
"""

import os
import re
import asyncio
import httpx
import subprocess
from dataclasses import dataclass
from typing import List, Optional


# ─── SRT 파싱 ─────────────────────────────────────────────────

@dataclass
class Subtitle:
    index: int
    start: float   # 초 단위
    end: float     # 초 단위
    text: str


def parse_srt(srt_path: str) -> List[Subtitle]:
    """SRT 파일을 파싱하여 Subtitle 리스트 반환"""
    subtitles = []

    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    # SRT 블록 분리
    blocks = re.split(r'\n\n+', content.strip())

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue

        try:
            index = int(lines[0].strip())
            time_line = lines[1].strip()
            text = ' '.join(lines[2:]).strip()

            # 타임코드 파싱 (00:00:01,000 --> 00:00:03,500)
            match = re.match(
                r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
                time_line
            )
            if not match:
                continue

            h1, m1, s1, ms1, h2, m2, s2, ms2 = match.groups()
            start = int(h1)*3600 + int(m1)*60 + int(s1) + int(ms1)/1000
            end   = int(h2)*3600 + int(m2)*60 + int(s2) + int(ms2)/1000

            subtitles.append(Subtitle(index=index, start=start, end=end, text=text))
        except (ValueError, AttributeError):
            continue

    return subtitles


def generate_srt_from_script(script: str, audio_duration: float, output_path: str):
    """
    스크립트 텍스트에서 SRT 자막 자동 생성
    (TTS 오디오가 있으면 Whisper로 생성하는 게 더 정확하지만,
     간단하게 글자 수 기반으로 균등 분배)
    """
    # 문장 단위로 분리
    sentences = re.split(r'(?<=[.!?])\s+|(?<=。)\s*', script.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        sentences = [script.strip()]

    # 각 문장에 시간 균등 배분
    duration_per = audio_duration / len(sentences)
    current_time = 0.0

    with open(output_path, "w", encoding="utf-8") as f:
        for i, sentence in enumerate(sentences, 1):
            start = current_time
            end = current_time + duration_per
            
            # SRT 타임코드 형식 변환
            def to_srt_time(t):
                h = int(t // 3600)
                m = int((t % 3600) // 60)
                s = int(t % 60)
                ms = int((t % 1) * 1000)
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

            f.write(f"{i}\n")
            f.write(f"{to_srt_time(start)} --> {to_srt_time(end)}\n")
            f.write(f"{sentence}\n\n")
            current_time = end

    print(f"[SRT] 자막 생성 완료: {output_path} ({len(sentences)}개 문장)")


# ─── 스톡 영상 다운로드 ────────────────────────────────────────

async def download_videos(video_urls: List[str], video_id: str) -> List[str]:
    """Pexels 영상 URL 목록을 다운로드하고 파일 경로 반환"""
    os.makedirs("tmp", exist_ok=True)
    paths = []

    async with httpx.AsyncClient(timeout=60) as client:
        for i, url in enumerate(video_urls):
            try:
                print(f"[Download] 영상 {i+1}/{len(video_urls)} 다운로드 중...")
                res = await client.get(url, follow_redirects=True)
                path = f"tmp/{video_id}_clip{i}.mp4"
                with open(path, "wb") as f:
                    f.write(res.content)
                paths.append(path)
                print(f"[Download] 완료: {path}")
            except Exception as e:
                print(f"[Download] 실패 ({url[:50]}...): {e}")

    return paths


# ─── ffmpeg 오디오 길이 조회 ───────────────────────────────────

def get_duration(file_path: str) -> float:
    """ffprobe로 미디어 파일 길이(초) 조회"""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


# ─── 핵심: 영상 합성 ───────────────────────────────────────────

async def compose_video(
    video_id: str,
    video_urls: List[str],
    audio_path: str,
    srt_path: Optional[str] = None,
    script: Optional[str] = None,
    output_dir: str = "output",
) -> str:
    """
    메인 합성 함수
    
    Args:
        video_id:    고유 ID
        video_urls:  Pexels 영상 URL 목록
        audio_path:  TTS 나레이션 MP3 경로
        srt_path:    SRT 자막 파일 경로 (없으면 script로 자동 생성)
        script:      나레이션 스크립트 (SRT 자동 생성용)
        output_dir:  출력 폴더
    
    Returns:
        완성 영상 파일 경로
    """
    os.makedirs("tmp", exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 1. 나레이션 길이 확인
    audio_duration = get_duration(audio_path)
    print(f"[Compose] 나레이션 길이: {audio_duration:.2f}초")

    # 2. SRT 자막 준비
    if not srt_path and script:
        srt_path = f"tmp/{video_id}.srt"
        generate_srt_from_script(script, audio_duration, srt_path)
    
    # 3. 스톡 영상 다운로드
    video_paths = await download_videos(video_urls, video_id)
    if not video_paths:
        raise Exception("다운로드된 영상이 없습니다.")

    # 4. 각 클립을 9:16으로 변환 + 루프 처리
    processed_clips = []
    for i, path in enumerate(video_paths):
        processed_path = f"tmp/{video_id}_processed{i}.mp4"
        clip_duration = get_duration(path)
        
        # 9:16 세로형 크롭 + 리사이즈
        crop_filter = (
            "scale=720:1280:force_original_aspect_ratio=increase,"
            "crop=720:1280"
        )
        
        subprocess.run([
            "ffmpeg", "-y",
            "-i", path,
            "-vf", crop_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-an",                # 오디오 제거 (나레이션으로 대체)
            "-r", "30",
            processed_path,
        ], capture_output=True)
        
        processed_clips.append(processed_path)
        print(f"[Compose] 클립 {i+1} 전처리 완료 ({clip_duration:.1f}초)")

    # 5. 클립 연결 + 오디오 길이에 맞게 루프
    concat_path = f"tmp/{video_id}_concat.mp4"
    _concat_and_loop(processed_clips, audio_duration, concat_path, video_id)

    # 6. 나레이션 + 자막 합성
    output_path = f"{output_dir}/{video_id}.mp4"
    _add_audio_and_subtitle(concat_path, audio_path, srt_path, output_path)

    # 7. 임시 파일 정리
    _cleanup(video_paths + processed_clips + [concat_path])

    print(f"[Compose] 최종 완성: {output_path}")
    return output_path


def _concat_and_loop(
    clip_paths: List[str],
    target_duration: float,
    output_path: str,
    video_id: str,
):
    """
    클립들을 이어 붙이고, 오디오 길이보다 짧으면 반복(Loop)
    """
    # 각 클립 길이 합산
    total = sum(get_duration(p) for p in clip_paths)
    print(f"[Concat] 총 클립 길이: {total:.1f}초 / 필요: {target_duration:.1f}초")

    # 클립이 부족하면 반복
    repeated_clips = []
    current = 0.0
    cycle = 0

    while current < target_duration:
        for path in clip_paths:
            if current >= target_duration:
                break
            repeated_clips.append(path)
            current += get_duration(path)
        cycle += 1
        if cycle > 20:  # 무한 루프 방지
            break

    print(f"[Concat] {len(repeated_clips)}개 클립 사용 (반복 {cycle}회)")

    # ffmpeg concat 리스트 파일 생성
    concat_list = f"tmp/{video_id}_concat_list.txt"
    with open(concat_list, "w") as f:
        for path in repeated_clips:
            abs_path = os.path.abspath(path).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    # ffmpeg concat
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list,
        "-t", str(target_duration),   # 정확히 오디오 길이만큼 자름
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-r", "30",
        output_path,
    ], capture_output=True)

    os.remove(concat_list)
    print(f"[Concat] 완료: {output_path}")


def _add_audio_and_subtitle(
    video_path: str,
    audio_path: str,
    srt_path: Optional[str],
    output_path: str,
):
    """
    영상에 나레이션 오디오와 SRT 자막 합성
    자막 스타일: 하단 중앙, 흰색 텍스트, 검정 외곽선, 반투명 배경
    """
    # 자막 필터 (가독성 최적화)
    if srt_path and os.path.exists(srt_path):
        abs_srt = os.path.abspath(srt_path).replace("\\", "/")
        # Windows 경로 처리
        if os.name == 'nt':
            abs_srt = abs_srt.replace(":", "\\:")

        subtitle_filter = (
            f"subtitles='{abs_srt}'"
            ":force_style='"
            "FontName=Malgun Gothic,"      # 한국어 폰트 (Linux: NanumGothic)
            "FontSize=22,"
            "PrimaryColour=&H00FFFFFF,"    # 흰색 텍스트
            "OutlineColour=&H00000000,"    # 검정 외곽선
            "BackColour=&H80000000,"       # 반투명 검정 배경
            "Outline=2,"
            "Shadow=1,"
            "Alignment=2,"                 # 하단 중앙
            "MarginV=60"                   # 하단에서 60px
            "'"
        )
        vf = subtitle_filter
    else:
        vf = None
        print("[Subtitle] SRT 파일 없음 — 자막 없이 합성")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-map", "0:v:0",
        "-map", "1:a:0",
    ]

    if vf:
        cmd += ["-vf", vf]

    cmd.append(output_path)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ffmpeg 오류] {result.stderr[-500:]}")
        raise Exception(f"ffmpeg 합성 실패: {result.stderr[-200:]}")

    print(f"[Audio+Subtitle] 합성 완료: {output_path}")


def _cleanup(paths: List[str]):
    """임시 파일 삭제"""
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


# ─── 단독 실행 테스트 ──────────────────────────────────────────

async def test():
    """로컬 테스트용"""
    import uuid

    video_id = str(uuid.uuid4())[:8]

    # 테스트용 Pexels 영상 URL (실제 URL로 교체)
    test_video_urls = [
        "https://www.pexels.com/download/video/854982/",
        "https://www.pexels.com/download/video/855264/",
    ]

    # 테스트용 오디오 (실제 TTS 파일로 교체)
    test_audio_path = "test_audio.mp3"

    # 테스트용 스크립트
    test_script = "안녕하세요! 오늘은 정말 특별한 이야기를 들려드리겠습니다. 함께 보시죠!"

    if not os.path.exists(test_audio_path):
        print("⚠ test_audio.mp3 파일이 없습니다. 실제 TTS 파일을 준비해주세요.")
        return

    output = await compose_video(
        video_id=video_id,
        video_urls=test_video_urls,
        audio_path=test_audio_path,
        script=test_script,
    )
    print(f"\n✅ 완성: {output}")


if __name__ == "__main__":
    asyncio.run(test())