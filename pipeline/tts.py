import os
from google.cloud import texttospeech
from dotenv import load_dotenv
load_dotenv()

async def generate_tts(text: str, language: str, video_id: str) -> str:
    client = texttospeech.TextToSpeechClient(
        client_options={"api_key": os.getenv("GOOGLE_TTS_API_KEY")}
    )
    voice_name = "ko-KR-Neural2-A" if language == "ko" else "en-US-Neural2-F"
    lang_code = "ko-KR" if language == "ko" else "en-US"

    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code=lang_code,
            name=voice_name,
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.1,
            volume_gain_db=2.0,
        ),
    )
    os.makedirs("tmp", exist_ok=True)
    path = f"tmp/{video_id}.mp3"
    with open(path, "wb") as f:
        f.write(response.audio_content)
    return path