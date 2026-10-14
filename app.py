import logging
import os

import streamlit as st
from groq import AuthenticationError, APIConnectionError, APIStatusError, RateLimitError
from streamlit.errors import StreamlitSecretNotFoundError

from media_engine import VideoError, groq_error_message, summarize_video

logger = logging.getLogger(__name__)


def get_setting(name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        return st.secrets.get(name)
    except StreamlitSecretNotFoundError:
        return None


st.set_page_config(page_title='SNS AI 요약기', page_icon='📝')
st.title('🎬 SNS 영상 AI 요약기')
st.caption('YouTube와 Instagram 영상의 자막 또는 음성을 한국어로 요약합니다.')
api_key = get_setting('GROQ_API_KEY')
if not api_key:
    api_key = st.text_input('Groq API Key를 입력하세요:', type='password')
url = st.text_input('요약할 영상 URL (YouTube / Instagram Reel):')
language_label = st.selectbox('영상 음성 언어', ['자동 감지', '한국어', '영어'])
language = {'자동 감지': None, '한국어': 'ko', '영어': 'en'}[language_label]

if st.button('요약 시작하기', type='primary'):
    if not api_key or not api_key.strip():
        st.warning('Groq API Key가 설정되지 않았습니다.')
    elif not url.strip():
        st.warning('영상 URL을 입력해주세요.')
    else:
        with st.status('영상 분석을 시작합니다.', expanded=True) as status:
            try:
                result = summarize_video(
                    url, api_key, cookies=get_setting('YOUTUBE_COOKIES'),
                    language=language, model=(get_setting('GROQ_MODEL') or 'llama-3.3-70b-versatile').strip(),
                    progress=status.write,
                )
                st.session_state['summary'] = result
                st.session_state['summary_url'] = url.strip()
                status.update(label='요약 완료!', state='complete', expanded=False)
            except Exception as exc:
                status.update(label='요약에 실패했습니다.', state='error')
                if isinstance(exc, VideoError):
                    message = str(exc)
                elif isinstance(exc, AuthenticationError):
                    message = 'Groq API 키가 유효하지 않습니다. 키 설정을 확인해주세요.'
                elif isinstance(exc, RateLimitError):
                    message = 'API 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.'
                elif isinstance(exc, APIConnectionError):
                    message = 'Groq 연결에 실패했습니다. 네트워크 접근을 확인해주세요.'
                elif isinstance(exc, APIStatusError):
                    message = groq_error_message(exc)
                else:
                    logger.error('Summary failed (%s)', type(exc).__name__)
                    message = '처리 중 오류가 발생했습니다. 설정을 확인하고 다시 시도해주세요.'
                st.error(message)

if st.session_state.get('summary'):
    st.markdown('### 📌 요약 결과')
    st.caption(f"요약한 영상: {st.session_state['summary_url']}")
    st.write(st.session_state['summary'])
    st.download_button('요약 다운로드', st.session_state['summary'], file_name='summary.md', mime='text/markdown')
