"""语音 API：语音转文字（Whisper）与文字转语音（TTS）"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from openai import AsyncOpenAI

from src.config.settings import LLM_CONFIG

router = APIRouter()


def _get_openai_client() -> AsyncOpenAI:
    api_key = LLM_CONFIG.get("openai_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置 OPENAI_API_KEY，无法使用语音功能")
    return AsyncOpenAI(
        api_key=api_key,
        base_url=LLM_CONFIG.get("openai_base_url"),
        max_retries=5,
        timeout=60,
    )


class SynthesizeRequest(BaseModel):
    """文字转语音请求"""
    text: str
    voice: str = "alloy"


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """语音转文字（Whisper）"""
    try:
        client = _get_openai_client()
        audio_bytes = await file.read()

        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(file.filename or "audio.webm", audio_bytes, file.content_type or "audio/webm"),
        )

        return {"status": "success", "text": transcript.text}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 语音转文字失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    """文字转语音（TTS）"""
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本内容为空")

    try:
        client = _get_openai_client()

        response = await client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=request.voice,
            input=text,
        )

        return Response(content=response.content, media_type="audio/mpeg")

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 文字转语音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
