import os
import re
import tempfile
import streamlit as st
from groq import Groq
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_PATH = None

def extract_youtube_id(url):
    """다양한 유튜브 URL 형태에서 11자리 Video ID 추출"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'youtu\.be\/([0-9A-Za-z_-]{11})',
        r'shorts\/([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def fetch_youtube_transcript(video_id):
    """모든 가능한 언어 자막 및 자동 생성 자막 강제 수집"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # 1. 수동 등록 자막 우선 탐색
        for lang in ['ko', 'en']:
            try:
                t = transcript_list.find_manually_created_transcript([lang])
                return " ".join([item['text'] for item in t.fetch()])
            except Exception:
                pass

        # 2. 자동 생성 자막 탐색
        for lang in ['ko', 'en']:
            try:
                t = transcript_list.find_generated_transcript([lang])
                return " ".join([item['text'] for item in t.fetch()])
            except Exception:
                pass

        # 3. 타 언어 자막을 한국어로 번역 시도
        for t in transcript_list:
            if t.is_translatable:
                return " ".join([item['text'] for item in t.translate('ko').fetch()])
            return " ".join([item['text'] for item in t.fetch()])
    except Exception:
        return ""
    return ""

def summarize_video(url, api_key):
    client = Groq(api_key=api_key)
    LLM_MODEL = "llama-3.3-70b-versatile"
    full_text = ""
    
    # 1. 유튜브 자막 우선 처리 (403 다운로드 원천 방지)
    if "youtube.com" in url or "youtu.be" in url:
        video_id = extract_youtube_id(url)
        if video_id:
            full_text = fetch_youtube_transcript(video_id)

    # 2. 자막이 없거나 인스타그램인 경우 오디오 추출
    if not full_text:
        cookie_file = None
        # Secrets에 쿠키가 있을 경우 임시 파일 생성
        raw_cookies = st.secrets.get("YOUTUBE_COOKIES", None)
        if raw_cookies:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
                f.write(raw_cookies)
                cookie_file = f.name

        ydl_opts = {
            'format': 'ba/b/worstaudio',
            'outtmpl': 'temp_audio.%(ext)s',
            'overwrites': True,
            'quiet': True,
            'socket_timeout': 15,
        }

        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        if FFMPEG_PATH:
            ydl_opts['ffmpeg_location'] = FFMPEG_PATH
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '32',
            }]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            if "403" in str(e) or "Forbidden" in str(e):
                raise RuntimeError(
                    "호스팅 서버 IP가 플랫폼에 의해 차단되었습니다(403 Forbidden).\n"
                    "- 유튜브: 공식/자동 자막이 켜져 있는 영상 링크로 테스트해 주세요.\n"
                    "- 인스타그램: 클라우드 환경에서는 차단되므로 로컬 PC 터미널에서 실행해야 합니다."
                ) from e
            raise e
        finally:
            if cookie_file and os.path.exists(cookie_file):
                os.remove(cookie_file)
            
        audio_path = None
        for ext in ['mp3', 'm4a', 'webm', 'opus']:
            if os.path.exists(f"temp_audio.{ext}"):
                audio_path = f"temp_audio.{ext}"
                break
        
        if not audio_path:
            raise FileNotFoundError("오디오 스트림을 생성하지 못했습니다.")

        try:
            file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            if file_size_mb > 20:
                raise ValueError(f"오디오 파일 용량({file_size_mb:.1f}MB)이 한도(20MB)를 초과했습니다.")

            with open(audio_path, "rb") as file:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_path), file.read()),
                    model="whisper-large-v3-turbo",
                    response_format="text",
                    language="ko"
                )
            full_text = str(transcription)
        finally:
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)

    if not full_text.strip():
        raise ValueError("영상에서 추출된 내용이 없습니다.")

    # 3. 요약 생성
    prompt = f"""
아래는 영상의 전체 내용입니다. 내용을 상세하고 입체적으로 요약해 주세요.

[작성 지침]
1. 📌 한 줄 핵심 요약: 전체 주제 1문장 정리
2. 💡 상세 핵심 내용: 최소 5~7개 이상의 상세 항목으로 구체적인 수치/예시 포함 작성
3. 🔑 핵심 키워드 & 용어: 3~5개 키워드와 의미
4. 🏁 결론 및 시사점: 최종 인사이트

[전체 텍스트]
{full_text}
"""

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "콘텐츠 요약 전문가로서 가독성 높은 한국어로 요약하세요."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content