import logging
import os

import streamlit as st
from google.genai import errors
import httpx
from streamlit.errors import StreamlitSecretNotFoundError

import video_engine
from video_engine import VideoError, DEFAULT_MODEL, gemini_error_message, summarize_video
from browser_keys import saved_browser_key

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
st.caption(f'앱 1.2.0 · 처리 모듈 {video_engine.ENGINE_VERSION}')
if not video_engine.is_current_source():
    st.error('업데이트된 파일과 실행 중인 처리 모듈이 다릅니다. Manage app에서 Reboot app을 실행한 뒤 새로고침해주세요.')
    st.stop()
configured_key = get_setting('GEMINI_API_KEY') or get_setting('GOOGLE_API_KEY')
with st.expander('🔑 Gemini API 키 설정', expanded=True):
    browser_key = saved_browser_key()
    with st.popover('저장 화면이 보이지 않으면 직접 입력'):
        manual_key = st.text_input('Gemini API Key (이번 접속에서만 사용)', type='password', key='manual_gemini_api_key')
        st.caption('이 입력란의 키는 브라우저를 다시 열면 재입력이 필요합니다. 다음 접속에도 사용하려면 위 저장 화면을 이용해주세요.')
    api_key = manual_key.strip() or browser_key or configured_key
    if manual_key.strip():
        st.caption('직접 입력한 키를 사용합니다.')
    elif browser_key:
        st.caption('이 브라우저에 저장된 키를 사용합니다.')
    elif configured_key:
        st.caption('서버에 설정된 키를 사용합니다. 개인 키를 저장하면 이 브라우저에서는 개인 키를 사용합니다.')
    else:
        st.info('API 키를 입력하고 이 브라우저에 저장을 눌러주세요. 저장 화면이 안 보이면 직접 입력을 이용해주세요.')
url = st.text_input('요약할 영상 URL (YouTube / Instagram Reel):')
language_label = st.selectbox('영상 음성 언어', ['자동 감지', '한국어', '영어'])
language = {'자동 감지': None, '한국어': 'ko', '영어': 'en'}[language_label]
model_options = [DEFAULT_MODEL]
configured_model = (get_setting('GEMINI_MODEL') or '').strip()
if configured_model and configured_model not in model_options:
    model_options.append(configured_model)
selected_model = st.selectbox('Gemini 모델', model_options, index=0)

if st.button('요약 시작하기', type='primary'):
    if not api_key or not api_key.strip():
        st.warning('Gemini API Key가 설정되지 않았습니다.')
    elif not url.strip():
        st.warning('영상 URL을 입력해주세요.')
    else:
        with st.status('영상 분석을 시작합니다.', expanded=True) as status:
            try:
                result = summarize_video(
                    url, api_key, cookies=get_setting('YOUTUBE_COOKIES'),
                    language=language, model=selected_model,
                    progress=status.write,
                )
                st.session_state['summary'] = result
                st.session_state['summary_url'] = url.strip()
                status.update(label='요약 완료!', state='complete', expanded=False)
            except Exception as exc:
                status.update(label='요약에 실패했습니다.', state='error')
                if isinstance(exc, VideoError):
                    message = str(exc)
                elif isinstance(exc, errors.APIError):
                    message = gemini_error_message(exc)
                elif isinstance(exc, httpx.RequestError):
                    message = 'Gemini 연결에 실패했습니다. 네트워크 접근을 확인해주세요.'
                else:
                    logger.error('Summary failed (%s)', type(exc).__name__)
                    message = '처리 중 오류가 발생했습니다. 설정을 확인하고 다시 시도해주세요.'
                st.error(message)

if st.session_state.get('summary'):
    st.markdown('### 📌 요약 결과')
    st.caption(f"요약한 영상: {st.session_state['summary_url']}")
    st.write(st.session_state['summary'])
    st.download_button('요약 다운로드', st.session_state['summary'], file_name='summary.md', mime='text/markdown')
