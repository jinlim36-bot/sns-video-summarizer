import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import media_engine as engine


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
            client.audio.transcriptions.create.return_value = 'transcript'
            result = engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', client)
            self.assertNotIn('language', client.audio.transcriptions.create.call_args.kwargs)
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
        client.audio.transcriptions.create.return_value = 'recognized'
        with patch.object(engine.yt_dlp, 'YoutubeDL', side_effect=factory), patch.object(engine, 'get_ffmpeg', return_value='/usr/bin/ffmpeg'), patch.object(engine, 'get_audio_duration', side_effect=[10, 3601]):
            self.assertEqual(engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', client), 'recognized')
            client.audio.transcriptions.create.reset_mock()
            with self.assertRaisesRegex(engine.VideoError, '60분'):
                engine.transcribe_audio('https://youtu.be/dQw4w9WgXcQ', client)
            client.audio.transcriptions.create.assert_not_called()
        self.assertTrue(all(not root.exists() for root in roots))

    def test_ffmpeg_duration_metadata(self):
        with patch.object(engine, 'get_ffmpeg', return_value='ffmpeg'), patch.object(engine.subprocess, 'run') as run:
            run.return_value = SimpleNamespace(returncode=1, stderr='Duration: 01:02:03.45, start: 0')
            self.assertAlmostEqual(engine.get_audio_duration(Path('audio.mp3')), 3723.45)
            run.return_value.stderr = 'Duration: N/A'
            with self.assertRaises(engine.VideoError):
                engine.get_audio_duration(Path('audio.mp3'))

    def test_oversized_request_is_split_and_retried(self):
        import httpx
        error = engine.APIStatusError('too large', response=httpx.Response(413, request=httpx.Request('POST', 'https://api.groq.com')), body={'error': {'code': 'request_too_large'}})
        good = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='짧은 요약'), finish_reason='stop')])
        client = MagicMock()
        client.chat.completions.create.side_effect = [error, good, good, good]
        self.assertEqual(engine.summarize_text('내용 ' * 700, client, 'model'), '짧은 요약')
        self.assertEqual(client.chat.completions.create.call_count, 4)

    def test_model_error_is_not_retried_and_body_is_not_exposed(self):
        import httpx
        error = engine.APIStatusError('model gone', response=httpx.Response(400, request=httpx.Request('POST', 'https://api.groq.com')), body={'error': {'code': 'model_decommissioned', 'message': 'private transcript'}})
        client = MagicMock()
        client.chat.completions.create.side_effect = error
        with self.assertRaises(engine.APIStatusError):
            engine.summarize_text('내용 ' * 700, client, 'missing-model')
        self.assertEqual(client.chat.completions.create.call_count, 1)
        message = engine.groq_error_message(error)
        self.assertIn('model_decommissioned', message)
        self.assertIn('HTTP 400', message)
        self.assertNotIn('private transcript', message)

    def test_long_text_summary_and_empty_response(self):
        client = MagicMock()
        def response(*args, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='요약'), finish_reason='stop')])
        client.chat.completions.create.side_effect = response
        self.assertEqual(engine.summarize_text('내용 ' * 5000, client, 'model'), '요약')
        self.assertGreater(client.chat.completions.create.call_count, 1)
        client.chat.completions.create.side_effect = None
        client.chat.completions.create.return_value = SimpleNamespace(choices=[])
        with self.assertRaises(engine.VideoError):
            engine.summarize_text('내용', client, 'model')


if __name__ == '__main__':
    unittest.main()
