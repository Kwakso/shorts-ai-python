import google.generativeai as genai
import os, json, re
from dotenv import load_dotenv
load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

STYLE_PROMPTS = {
    "cinematic": "Cinematic film quality, dramatic lighting, Hollywood style",
    "documentary": "Documentary style, natural lighting, realistic",
    "realistic": "Photorealistic, 8K, sharp focus, natural lighting",
    "cartoon": "Colorful cartoon style, bright colors, Pixar-like",
}

async def generate_script(topic: str, style: str, language: str = "ko") -> dict:
    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        generation_config={
            "max_output_tokens": 2048,
            "temperature": 0.7,
            "response_mime_type": "application/json",
        }
    )
    style_guide = STYLE_PROMPTS.get(style, STYLE_PROMPTS["documentary"])
    lang = "한국어" if language == "ko" else "English"

    prompt = f"""주제:"{topic}" 스타일:{style} 언어:{lang}
다음 JSON으로만 응답:
{{
  "title": "#Shorts 포함 30자 이내",
  "description": "100자 이내 해시태그 포함",
  "script": "50자 이내 나레이션",
  "searchKeywords": ["english1", "english2", "english3"],
  "tags": ["태그1", "Shorts", "YouTubeShorts"]
}}"""

    response = model.generate_content(prompt)
    text = re.sub(r'```json\n?|```\n?', '', response.text).strip()
    return json.loads(text)