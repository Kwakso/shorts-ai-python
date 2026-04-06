import google.genai as genai
import os, json, re
from dotenv import load_dotenv
load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

STYLE_PROMPTS = {
    "cinematic":   "Cinematic film quality, dramatic lighting, Hollywood style",
    "documentary": "Documentary style, natural lighting, realistic environment",
    "realistic":   "Photorealistic, 8K, sharp focus, natural lighting",
    "cartoon":     "Colorful cartoon style, bright colors, Pixar-like quality",
}

async def generate_script(topic: str, style: str, language: str = "ko") -> dict:
    style_guide = STYLE_PROMPTS.get(style, STYLE_PROMPTS["documentary"])
    lang = "한국어" if language == "ko" else "English"

    prompt = f"""너는 YouTube Shorts 전문 기획자야.
주제: "{topic}"
스타일: {style} ({style_guide})
언어: {lang}

아래 JSON 형식으로만 응답해. 다른 텍스트는 절대 포함하지 마.

{{
  "title": "클릭을 유도하는 제목 (30자 이내, #Shorts 포함)",
  "description": "영상 설명 (150자 이내, 해시태그 5개 포함)",
  "tags": ["태그1", "태그2", "Shorts", "YouTubeShorts"],
  "scenes": [
    {{
      "order": 1,
      "type": "hook",
      "script": "시청자를 바로 사로잡는 강렬한 첫 문장 (30~50자, {lang})",
      "searchKeyword": "pexels search keyword in English (2~3 words)",
      "duration": 5
    }},
    {{
      "order": 2,
      "type": "body",
      "script": "핵심 내용 첫 번째 (50~80자, {lang})",
      "searchKeyword": "pexels search keyword in English (2~3 words)",
      "duration": 10
    }},
    {{
      "order": 3,
      "type": "body",
      "script": "핵심 내용 두 번째 (50~80자, {lang})",
      "searchKeyword": "pexels search keyword in English (2~3 words)",
      "duration": 10
    }},
    {{
      "order": 4,
      "type": "body",
      "script": "핵심 내용 세 번째 (50~80자, {lang})",
      "searchKeyword": "pexels search keyword in English (2~3 words)",
      "duration": 10
    }},
    {{
      "order": 5,
      "type": "cta",
      "script": "마무리 + 좋아요/구독 유도 (30~50자, {lang})",
      "searchKeyword": "pexels search keyword in English (2~3 words)",
      "duration": 5
    }}
  ]
}}

중요 규칙:
1. scenes 배열은 반드시 5개 (hook 1개 + body 3개 + cta 1개)
2. 각 scene의 script는 반드시 {lang}로 작성
3. searchKeyword는 반드시 영어로 작성 (Pexels 검색용)
4. searchKeyword는 주제와 직접 관련된 구체적인 단어 사용
5. 전체 script 합산 300자 이상
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=4096,
            temperature=0.7,
        ),
    )

    text = re.sub(r'```json\n?|```\n?', '', response.text).strip()

    # 디버그 로그
    try:
        parsed = json.loads(text)
        scenes = parsed.get("scenes", [])
        total_chars = sum(len(s.get("script", "")) for s in scenes)
        total_duration = sum(s.get("duration", 0) for s in scenes)
        print(f"[Gemini] 제목: {parsed.get('title', '')}")
        print(f"[Gemini] Scene 수: {len(scenes)}개")
        print(f"[Gemini] 전체 스크립트: {total_chars}자")
        print(f"[Gemini] 총 예상 시간: {total_duration}초")
        for s in scenes:
            print(f"  [{s['type']}] {s['script'][:30]}... | 키워드: {s['searchKeyword']}")
        return parsed
    except json.JSONDecodeError as e:
        print(f"[Gemini 파싱 오류] {e}")
        print(f"[Gemini 원문] {text[:500]}")
        raise Exception(f"Gemini JSON 파싱 실패: {e}")


def get_full_script(script_data: dict) -> str:
    """scenes 배열에서 전체 나레이션 텍스트 추출"""
    scenes = script_data.get("scenes", [])
    return " ".join(s.get("script", "") for s in scenes)


def get_search_keywords(script_data: dict) -> list:
    """scenes 배열에서 scene별 searchKeyword 리스트 추출"""
    scenes = script_data.get("scenes", [])
    return [s.get("searchKeyword", "") for s in scenes]