import unittest
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import video_engine as engine


class MediaTests(unittest.TestCase):
    def test_supported_urls(self):
        for url in ['https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                    'https://youtu.be/dQw4w9WgXcQ',
                    'https://www.youtube.com/shorts/dQw4w9WgXcQ']:
            self.assertEqual(engine.extract_youtube_id(url), 'dQw4w9WgXcQ')
            self.assertEqual(engine.validate_video_url(url), url)
        engine.validate_video_url('https://www.instagram.com/reel/abc123/')

    def test_rejects_invalid_urls(self):
        for url in ['https://example.com/abcdefghijk', 'https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ',
                    'https://youtube.com/abcdefghijk/watch?v=dQw4w9WgXcQ',
                    'https://youtu.be/dQw4w9WgXcQextra', 'http://youtu.be/dQw4w9WgXcQ',
                    'https://user@youtu.be/dQw4w9WgXcQ', 'https://www.instagram.com/profile/']:
            with self.subTest(url=url), self.assertRaises(engine.VideoError):
                engine.validate_video_url(url)

    def test_modern_transcripts_preserve_times(self):
        track = SimpleNamespace(is_generated=False, language_code='en',
                                fetch=lambda: [SimpleNamespace(text='hello', start=65.5)])
        with patch.object(engine, 'YouTubeTranscriptApi') as api:
            api.return_value.list.return_value = [track]
            self.assertEqual(engine.fetch_youtube_transcript('dQw4w9WgXcQ'), '[1:05] hello')

    def test_transcript_absence_vs_failure(self):
        with patch.object(engine, 'YouTubeTranscriptApi') as api:
            api.return_value.list.side_effect = engine.TranscriptsDisabled('dQw4w9WgXcQ')
            self.assertEqual(engine.fetch_youtube_transcript('dQw4w9WgXcQ'), '')
            api.return_value.list.side_effect = RuntimeError('network denied')
            with self.assertRaises(engine.VideoError):
                engine.fetch_youtube_transcript('dQw4w9WgXcQ')

    def test_downloads_are_isolated_and_cleaned(self):
        directories = []

        class Downloader:
            def __init__(self, options):
                self.options = options
                directories.append(Path(options['outtmpl']).parent)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def extract_info(self, *args, **kwargs):
                return {'duration': 10}
            def process_ie_result(self, info, download):
                path = Path(self.options['outtmpl'].replace('%(ext)s', 'mp3'))
                path.write_bytes(b'audio')
                return {'filepath': str(path)}

        def run(_):
            client = MagicMock()
            client.models.generate_content.return_value = SimpleNamespace(text='transcript', candidates=[])
            result = engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', client)
            self.assertIn('원래 언어를 감지', client.models.generate_content.call_args.kwargs['contents'][1])
            return result

        with patch.object(engine.yt_dlp, 'YoutubeDL', Downloader), patch.object(engine, 'get_ffmpeg', return_value='/usr/bin/ffmpeg'), patch.object(engine, 'get_audio_duration', return_value=10):
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(run, range(2))), ['transcript', 'transcript'])
        self.assertEqual(len(set(directories)), 2)
        self.assertTrue(all(not p.exists() for p in directories))

    def test_download_failure_cleans_partial_files(self):
        roots = []
        downloader = MagicMock()
        def fail(*args, **kwargs):
            root = Path(roots[0])
            (root / 'audio.part').write_bytes(b'partial')
            raise RuntimeError('403')
        downloader.__enter__.return_value = downloader
        downloader.extract_info.side_effect = fail
        def factory(options):
            roots.append(Path(options['outtmpl']).parent)
            return downloader
        with patch.object(engine.yt_dlp, 'YoutubeDL', side_effect=factory), patch.object(engine, 'get_ffmpeg', return_value='/usr/bin/ffmpeg'):
            with self.assertRaises(engine.VideoError):
                engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', MagicMock(), cookies='test-only')
        self.assertFalse(roots[0].exists())

    def test_long_video_rejected_before_download(self):
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.extract_info.return_value = {'duration': 3601}
        with patch.object(engine.yt_dlp, 'YoutubeDL', return_value=downloader), patch.object(engine, 'get_ffmpeg', return_value='/usr/bin/ffmpeg'):
            with self.assertRaises(engine.VideoError):
                engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', MagicMock())
        downloader.process_ie_result.assert_not_called()

    def test_missing_duration_downloads_then_checks_audio(self):
        roots = []
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.extract_info.return_value = {'duration': None}
        def download(info, download):
            path = roots[-1] / 'audio.mp3'
            path.write_bytes(b'audio')
            return {'filepath': str(path)}
        downloader.process_ie_result.side_effect = download
        def factory(options):
            roots.append(Path(options['outtmpl']).parent)
            return downloader
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(text='recognized', candidates=[])
        with patch.object(engine.yt_dlp, 'YoutubeDL', side_effect=factory), patch.object(engine, 'get_ffmpeg', return_value='/usr/bin/ffmpeg'), patch.object(engine, 'get_audio_duration', side_effect=[10, 3601]):
            self.assertEqual(engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', client), 'recognized')
            client.models.generate_content.reset_mock()
            with self.assertRaisesRegex(engine.VideoError, '60분'):
                engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', client)
            client.models.generate_content.assert_not_called()
        self.assertTrue(all(not root.exists() for root in roots))

    def test_ffmpeg_duration_metadata(self):
        with patch.object(engine, 'get_ffmpeg', return_value='ffmpeg'), patch.object(engine.subprocess, 'run') as run:
            run.return_value = SimpleNamespace(returncode=1, stderr='Duration: 01:02:03.45, start: 0')
            self.assertAlmostEqual(engine.get_audio_duration(Path('audio.mp3')), 3723.45)
            run.return_value.stderr = 'Duration: N/A'
            with self.assertRaises(engine.VideoError):
                engine.get_audio_duration(Path('audio.mp3'))

    def test_oversized_request_is_split_and_retried(self):
        error = engine.errors.APIError(413, {'error': {'code': 413, 'message': 'too large'}})
        good = SimpleNamespace(text='짧은 요약', candidates=[])
        client = MagicMock()
        client.models.generate_content.side_effect = [error, good, good, good]
        self.assertEqual(engine.summarize_text('내용 ' * 700, client, 'model'), '짧은 요약')
        self.assertEqual(client.models.generate_content.call_count, 4)

    def test_no_available_fallback_preserves_error_and_hides_body(self):
        error = engine.errors.APIError(404, {'error': {'code': 404, 'message': 'private transcript'}})
        client = MagicMock()
        client.models.generate_content.side_effect = error
        client.models.list.return_value = []
        with self.assertRaises(engine.errors.APIError):
            engine.summarize_text('내용', client, 'missing-model')
        self.assertEqual(client.models.generate_content.call_count, 1)
        message = engine.gemini_error_message(error)
        self.assertIn('HTTP 404', message)
        self.assertNotIn('private transcript', message)

    def test_missing_model_uses_listed_generation_model(self):
        error = engine.errors.APIError(404, {'error': {'code': 404}})
        client = MagicMock()
        client.models.list.return_value = [SimpleNamespace(name='models/gemini-embedding-001', supported_actions=['embedContent']), SimpleNamespace(name='models/gemini-2.5-flash', supported_actions=['generateContent'])]
        client.models.generate_content.side_effect = [error, SimpleNamespace(text='요약 완료', candidates=[])]
        notices = []
        self.assertEqual(engine.summarize_text('영상 내용', client, 'missing-model', progress=notices.append), '요약 완료')
        self.assertEqual(client.models.generate_content.call_args.kwargs['model'], 'gemini-2.5-flash')
        self.assertIn('gemini-2.5-flash', notices[0])
        client.models.list.assert_called_once()

    def test_model_fallback_is_bounded(self):
        error = engine.errors.APIError(404, {'error': {'code': 404}})
        client = MagicMock()
        client.models.list.return_value = [SimpleNamespace(name='models/gemini-2.5-flash', supported_actions=['generateContent'])]
        client.models.generate_content.side_effect = error
        with self.assertRaises(engine.errors.APIError):
            engine.summarize_text('영상 내용', client, 'missing-model')
        self.assertEqual(client.models.generate_content.call_count, 2)
        client.models.list.assert_called_once()

    def test_audio_is_sent_directly_without_files_api(self):
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(text='전사 완료', candidates=[])
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'audio.mp3'
            path.write_bytes(b'audio-test-data')
            self.assertEqual(engine.GeminiService(client).transcribe(path), '전사 완료')
        contents = client.models.generate_content.call_args.kwargs['contents']
        self.assertEqual(contents[0].inline_data.data, b'audio-test-data')
        self.assertEqual(contents[0].inline_data.mime_type, 'audio/mpeg')
        client.files.upload.assert_not_called()
        client.files.get.assert_not_called()
        client.files.delete.assert_not_called()

    def test_inline_audio_failure_does_not_upload_a_file(self):
        client = MagicMock()
        client.models.generate_content.side_effect = engine.errors.APIError(403, {'error': {'code': 403}})
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'audio.mp3'
            path.write_bytes(b'audio')
            with self.assertRaises(engine.errors.APIError):
                engine.GeminiService(client).transcribe(path)
        client.files.upload.assert_not_called()
        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_invalid_key_is_explained_without_echoing_key(self):
        error = engine.errors.APIError(400, {'error': {'code':400, 'message':'secret value', 'details':[{'reason':'API_KEY_INVALID'}]}})
        message = engine.gemini_error_message(error)
        self.assertIn('유효하지', message)
        self.assertNotIn('secret value', message)

    def test_real_gemini_sdk_request_and_response_serialization(self):
        import httpx
        import json
        requests_seen = []
        def handle(request):
            requests_seen.append(request)
            return httpx.Response(200, json={'candidates': [{'content': {'role': 'model', 'parts': [{'text': 'SDK 요약'}]}, 'finishReason': 'STOP'}]})
        http_client = httpx.Client(transport=httpx.MockTransport(handle))
        with engine.genai.Client(api_key='test-key-not-real', http_options=engine.types.HttpOptions(httpx_client=http_client)) as client:
            self.assertEqual(engine.summarize_text('원문 내용', client), 'SDK 요약')
        body = json.loads(requests_seen[0].content)
        self.assertIn('gemini-2.5-flash:generateContent', str(requests_seen[0].url))
        self.assertEqual(body['generationConfig']['maxOutputTokens'], 4096)
        self.assertIn('원문 내용', body['contents'][0]['parts'][0]['text'])

    def test_long_audio_is_split_before_gemini_transcription(self):
        roots = []
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.extract_info.return_value = {'duration': 620}
        def factory(options):
            roots.append(Path(options['outtmpl']).parent)
            audio = roots[-1] / 'audio.mp3'
            audio.write_bytes(b'audio')
            downloader.process_ie_result.return_value = {'filepath': str(audio)}
            return downloader
        clips = []
        def split(command, **kwargs):
            clips.append(command)
            Path(command[-1]).write_bytes(b'clip')
        service = MagicMock()
        service.transcribe.side_effect = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth']
        with patch.object(engine.yt_dlp, 'YoutubeDL', side_effect=factory), patch.object(engine, 'get_ffmpeg', return_value='/usr/bin/ffmpeg'), patch.object(engine, 'get_audio_duration', return_value=620), patch.object(engine.subprocess, 'run', side_effect=split):
            result = engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', MagicMock(), service=service)
        self.assertEqual(result, 'first\nsecond\nthird\nfourth\nfifth\nsixth')
        self.assertEqual([command[command.index('-ss') + 1] for command in clips], ['0', '120', '240', '360', '480', '600'])
        self.assertEqual(service.transcribe.call_count, 6)
        self.assertFalse(roots[0].exists())

    def test_504_retries_then_succeeds(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [engine.errors.APIError(504, {'error': {'code': 504}}), SimpleNamespace(text='복구된 응답', candidates=[])]
        notices = []
        with patch.object(engine.time, 'sleep') as sleep:
            service = engine.GeminiService(client, progress=notices.append)
            self.assertEqual(service.generate('내용', '요약'), '복구된 응답')
        self.assertEqual(client.models.generate_content.call_count, 2)
        sleep.assert_called_once_with(1)
        self.assertTrue(any('다시 시도' in text for text in notices))

    def test_transient_retries_stop_and_auth_is_not_retried(self):
        client = MagicMock()
        client.models.generate_content.side_effect = engine.errors.APIError(504, {'error': {'code': 504}})
        with patch.object(engine.time, 'sleep'), self.assertRaises(engine.errors.APIError):
            engine.GeminiService(client).generate('내용', '요약')
        self.assertEqual(client.models.generate_content.call_count, 3)
        client.models.generate_content.reset_mock()
        client.models.generate_content.side_effect = engine.errors.APIError(403, {'error': {'code': 403}})
        with patch.object(engine.time, 'sleep') as sleep, self.assertRaises(engine.errors.APIError):
            engine.GeminiService(client).generate('내용', '요약')
        self.assertEqual(client.models.generate_content.call_count, 1)
        sleep.assert_not_called()

    def test_504_audio_is_split_in_order_and_temp_files_are_removed(self):
        roots = []
        downloader = MagicMock()
        downloader.__enter__.return_value = downloader
        downloader.extract_info.return_value = {'duration': 80}
        def factory(options):
            roots.append(Path(options['outtmpl']).parent)
            audio = roots[-1] / 'audio.mp3'
            audio.write_bytes(b'audio')
            downloader.process_ie_result.return_value = {'filepath': str(audio)}
            return downloader
        clips = []
        def split(command, **kwargs):
            clips.append(command)
            Path(command[-1]).write_bytes(b'clip')
        service = MagicMock()
        service.transcribe.side_effect = [engine.errors.APIError(504, {'error': {'code':504}}), '앞부분', '뒷부분']
        with patch.object(engine.yt_dlp, 'YoutubeDL', side_effect=factory), patch.object(engine, 'get_ffmpeg', return_value='/usr/bin/ffmpeg'), patch.object(engine, 'get_audio_duration', return_value=80), patch.object(engine.subprocess, 'run', side_effect=split):
            result = engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', MagicMock(), service=service)
        self.assertEqual(result, '앞부분\n뒷부분')
        self.assertEqual([command[command.index('-ss') + 1] for command in clips], ['0', '40.0'])
        self.assertFalse(roots[0].exists())

    def test_real_sdk_503_fallback_with_inline_audio(self):
        import httpx
        import json
        import base64
        requests_seen = []
        count = 0
        def handle(request):
            nonlocal count
            requests_seen.append(request)
            if request.method == 'GET':
                return httpx.Response(200, json={'models': [{'name': 'models/gemini-2.5-flash-lite', 'supportedGenerationMethods': ['generateContent']}]})
            count += 1
            if count <= 2:
                return httpx.Response(503, json={'error': {'code':503, 'status':'UNAVAILABLE', 'message':'overloaded'}})
            return httpx.Response(200, json={'candidates': [{'content': {'role': 'model', 'parts': [{'text':'전사 복구'}]}, 'finishReason':'STOP'}]})
        http_client = httpx.Client(transport=httpx.MockTransport(handle))
        notices = []
        with tempfile.TemporaryDirectory() as root, patch.object(engine.time, 'sleep'):
            path = Path(root) / 'audio.mp3'
            path.write_bytes(b'audio-test-data')
            with engine.genai.Client(api_key='test-key-not-real', http_options=engine.types.HttpOptions(httpx_client=http_client, retry_options=engine.types.HttpRetryOptions(attempts=1))) as client:
                service = engine.GeminiService(client, progress=notices.append)
                self.assertEqual(service.transcribe(path), '전사 복구')
                self.assertEqual(service.model, 'gemini-2.5-flash-lite')
        self.assertEqual(count, 3)
        self.assertEqual(len(requests_seen), 4)
        body = json.loads(requests_seen[-1].content)
        audio = body['contents'][0]['parts'][0]['inlineData']
        self.assertEqual(audio['mime_type'], 'audio/mpeg')
        self.assertEqual(base64.b64decode(audio['data']), b'audio-test-data')
        self.assertIn('gemini-2.5-flash-lite:generateContent', str(requests_seen[-1].url))
        self.assertFalse(any('/upload/' in str(request.url) for request in requests_seen))

    def test_pipeline_error_identifies_transcription_stage_without_raw_body(self):
        error = engine.errors.APIError(503, {'error': {'code':503, 'message':'private transcript'}})
        with patch.object(engine.genai, 'Client'), patch.object(engine, 'transcribe_audio', side_effect=error):
            with self.assertRaises(engine.VideoError) as raised:
                engine.summarize_video('https://www.instagram.com/reel/test/', 'test-key')
        self.assertIn('오디오 전사 단계', str(raised.exception))
        self.assertIn('HTTP 503', str(raised.exception))
        self.assertNotIn('private transcript', str(raised.exception))

    def test_long_text_summary_and_empty_response(self):
        client = MagicMock()
        def response(*args, **kwargs):
            return SimpleNamespace(text='요약', candidates=[])
        client.models.generate_content.side_effect = response
        self.assertEqual(engine.summarize_text('내용 ' * 5000, client, 'model'), '요약')
        self.assertGreater(client.models.generate_content.call_count, 1)
        client.models.generate_content.side_effect = None
        client.models.generate_content.return_value = SimpleNamespace(text=None, candidates=[])
        with self.assertRaises(engine.VideoError):
            engine.summarize_text('내용', client, 'model')


if __name__ == '__main__':
    unittest.main()
