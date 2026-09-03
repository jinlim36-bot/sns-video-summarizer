import os
import re
from groq import Groq
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp

# imageio_ffmpeg가 설치되어 있으면 ffmpeg 경로 자동 확보
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_PATH = None

def extract_youtube_id(url):
    """유튜브 URL에서 Video ID만 추출하는 함수"""
    pattern = r"(?:v=|\/([0-9A-Za-z_-]{11}).*|list=)"
    match = re.search(pattern, url)
    return match.group(1) if match else None

def summarize_video(url, api_key):
    client = Groq(api_key=api_key)
    LLM_MODEL = "llama-3.3-70b-versatile"
    
    full_text = ""
    
    # 1. 유튜브 자막 추출 우선 시도
    if "youtube.com" in url or "youtu.be" in url:
        video_id = extract_youtube_id(url)
        if video_id:
            try:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
                full_text = " ".join([item['text'] for item in transcript_list])
            except Exception:
                pass  # 자막 추출 실패 시 오디오 다운로드 방식으로 전환

    # 2. 인스타그램 릴스 / 자막 없는 영상 (Groq Whisper 음성인식 처리)
    if not full_text:
        ydl_opts = {
            'format': 'bestaudio/worst/worstaudio',
            'outtmpl': 'temp_audio.%(ext)s',
            'overwrites': True,
            'quiet': True,
            # 클라우드 환경 403 Forbidden 에러 우회
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios']
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            },
            'socket_timeout': 30,
        }

        # FFmpeg가 감지되면 32kbps MP3로 고강도 오디오 압축 적용
        if FFMPEG_PATH:
            ydl_opts['ffmpeg_location'] = FFMPEG_PATH
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '32',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # 다운로드된 오디오 파일 탐색
        audio_path = None
        for ext in ['mp3', 'm4a', 'webm', 'opus']:
            if os.path.exists(f"temp_audio.{ext}"):
                audio_path = f"temp_audio.{ext}"
                break
        
        if not audio_path:
            raise FileNotFoundError("오디오 파일을 추출하지 못했습니다.")

        try:
            # Groq 서버 전송 전 용량 체크 (20MB 한도 방어)
            file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            if file_size_mb > 20:
                raise ValueError(
                    f"음성 파일 용량({file_size_mb:.1f}MB)이 API 한도(20MB)를 초과했습니다. "
                    f"더 짧은 영상으로 시도해 주세요."
                )

            # Groq Whisper 모델로 음성 -> 텍스트 변환
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

    # 3. Groq Llama 3.3 모델로 한국어 요약 생성
    prompt = f"""
아래는 영상의 전체 음성/자막 텍스트입니다. 
영상을 직접 보지 않은 사람도 내용을 완벽하게 이해할 수 있도록, 생략 없이 **상세하고 입체적으로** 요약해 주세요.

[작성 지침]
1. **📌 한 줄 핵심 요약**: 전체 영상의 주제와 핵심 메시지를 한 문장으로 명확히 정리
2. **💡 상세 핵심 내용 (구체적 요약)**:
   - 영상의 전체 흐름과 주요 내용을 최소 5~7개 이상의 상세 항목으로 작성하세요.
   - 단순 요약을 넘어 영상에서 언급된 **구체적인 수치, 예시, 핵심 팁, 이유**를 함께 기술하세요.
3. **🔑 핵심 키워드 & 용어**: 영상에서 가장 중요하게 다뤄진 키워드 3~5개와 그 의미
4. **🏁 결론 및 시사점**: 작성자가 전달하려는 최종 결론과 시청자가 얻을 수 있는 인사이트

[전체 텍스트]
{full_text}
"""

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": "당신은 전문 콘텐츠 에디터이자 요약 전문가입니다. 자연스럽고 가독성 높은 한국어로 풍부한 상세 요약을 작성하세요."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3
    )
    return response.choices[0].message.content