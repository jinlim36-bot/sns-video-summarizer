import streamlit as st
from media_engine import summarize_video

st.set_page_config(page_title="SNS AI 요약기", page_icon="📝")
st.title("🎬 SNS 영상 AI 요약기")
st.caption("유튜브, 인스타그램 릴스 링크를 넣으시면 AI가 핵심 내용을 요약해 드립니다.")

# 1. Streamlit Secrets에서 API 키 조회 시도
api_key = st.secrets.get("GROQ_API_KEY", None)

# 2. Secrets에 키가 설정되어 있지 않은 경우에만 화면에 입력창 표시
if not api_key:
    api_key = st.text_input("Groq API Key를 입력하세요:", type="password")

url = st.text_input("요약할 영상 URL (YouTube / Instagram Reel):")

if st.button("요약 시작하기", type="primary"):
    if not api_key:
        st.warning("Groq API Key가 설정되지 않았습니다.")
    elif not url:
        st.warning("영상 URL을 입력해주세요.")
    else:
        with st.spinner("영상을 분석하는 중입니다... (약 10~30초 소요)"):
            try:
                result = summarize_video(url, api_key)
                st.success("요약 완료!")
                st.markdown("### 📌 요약 결과")
                st.write(result)
            except Exception as e:
                st.error(f"🚨 발생한 오류 메시지:\n\n{e}")