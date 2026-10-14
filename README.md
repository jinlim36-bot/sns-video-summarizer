# SNS 영상 AI 요약기

YouTube 자막 또는 YouTube/Instagram 오디오를 이용해 한국어 요약을 만드는 Streamlit 앱입니다. Groq API로 음성 인식과 요약을 수행합니다.

## 실행

Python 3.12에서 검증했습니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Groq 키는 `GROQ_API_KEY` 환경변수, Streamlit secrets, 화면의 비밀번호 입력란 순으로 조회합니다. secrets 파일이 없어도 실행할 수 있습니다. 키와 쿠키는 Git에 커밋하지 마세요.

선택 설정:

- `GROQ_MODEL`: 요약 모델. 기본값 `llama-3.3-70b-versatile`.
- `YOUTUBE_COOKIES`: 인증이 필요한 영상에 사용하는 Netscape 형식 쿠키 텍스트. 다운로드 작업의 임시 디렉터리에만 저장하고 작업 종료 시 삭제합니다.

## 동작과 제한

- HTTPS YouTube 영상 및 Instagram 릴스/게시물 URL을 검증합니다. 플레이리스트와 진행 중인 라이브 방송의 오디오 처리는 지원하지 않습니다.
- YouTube 자막이 없는 경우 오디오를 다운로드합니다. 자막 조회 접근 오류는 원인을 숨긴 채 다운로드로 넘어가지 않고 안내합니다.
- 오디오 처리 대상은 60분 이하 영상입니다. 플랫폼 길이 정보가 없으면 다운로드를 진행하고, 변환된 오디오의 실제 길이를 FFmpeg로 확인합니다. 다운로드 중 100MB 제한, 변환 오디오 20MB 제한을 적용합니다. 소켓 타임아웃 및 재시도 제한과 다운로드 진행 시 3분 제한을 적용하지만 전체 작업 시간을 보장하는 제한은 아닙니다.
- 음성 언어는 기본적으로 자동 감지하며 한국어/영어를 선택할 수 있습니다.
- 긴 자막은 나누어 요약한 뒤 합칩니다. 텍스트는 240,000자까지 처리하며 긴 영상은 API 호출 횟수와 비용이 증가합니다.
- 자막의 시간 표시는 보존합니다. 음성 인식 결과에는 시간 표시를 생성하지 않습니다.
- 결과는 세션에 유지되며 Markdown으로 다운로드할 수 있습니다. 새 작업 실패 시 이전 결과와 그 영상 URL이 유지됩니다.
- 영상 공개 여부, 플랫폼의 접근 제한, 네트워크 정책, Groq 인증 및 사용량 한도에 따라 실제 처리에 실패할 수 있습니다.

## 테스트

```bash
python -m unittest discover -s tests -v
python -m pip check
```

테스트는 외부 API를 대체해 URL 검증, 최신 자막 응답, 자막 오류 구분, 동시 다운로드 파일 격리, 실패 시 정리, 영상 길이 제한, 긴 텍스트 요약, 키 조회와 화면 결과 유지 등을 검증합니다. 실제 외부 영상 다운로드와 Groq 호출은 유효한 키와 네트워크 접근이 있는 환경에서 별도로 확인해야 합니다.

## Streamlit Cloud 자동 방문

GitHub Actions의 `Keep Streamlit Alive` 워크플로가 2시간마다 브라우저로 앱을 방문합니다. 슬립 화면이면 깨우기 버튼을 누르고, 실제 앱 제목과 요약 버튼이 표시되는지 확인한 뒤 60초 동안 세션을 유지합니다. 요약 버튼을 누르거나 Groq API를 호출하지 않습니다.

1. 기본 대상은 `https://sns-video-summarizer-hukphapjbrrte5n87fyat9.streamlit.app`입니다. 주소가 바뀌면 GitHub 저장소의 **Settings → Secrets and variables → Actions → Variables**에 `STREAMLIT_APP_URL`을 등록해 덮어쓸 수 있습니다.
2. **Actions → Keep Streamlit Alive → Run workflow**로 수동 실행해 성공 여부를 확인합니다.
3. 기본 브랜치에 워크플로가 있어야 정기 실행됩니다. 저장소에서 Actions가 허용되어 있어야 합니다.

예약 실행은 지연되거나 누락될 수 있고, 공개 저장소는 60일간 저장소 활동이 없으면 예약 워크플로가 비활성화될 수 있습니다. 플랫폼이 자동 방문을 실제 사용자 활동으로 인정하는지도 보장할 수 없으므로 이 작업은 상시 가동을 보장하지 않습니다. 지속 가동이 필수라면 상시 실행을 지원하는 호스팅을 사용하세요. 비공개 앱의 로그인 화면은 이 워크플로로 통과하지 않습니다.

Groq 요약 입력 한도 오류(413 등)는 입력을 더 작은 구간으로 나누어 제한된 횟수만 재시도합니다. 그 외 모델/권한/서비스 오류는 HTTP 상태와 알려진 오류 코드를 안내하며 원문이 포함될 수 있는 API 응답 전문은 표시하지 않습니다.

요약 모델이 없거나 폐기된 경우 계정의 `/models` 목록을 조회해 지원하는 대체 요약 모델로 전환하고 화면에 알립니다. 후보는 `llama-3.1-8b-instant`, `llama-3.3-70b-versatile`, `openai/gpt-oss-20b`, `openai/gpt-oss-120b` 순이며, 목록에 없는 모델과 음성 모델은 선택하지 않습니다. 대체 모델도 사용할 수 없으면 오류를 표시합니다.
