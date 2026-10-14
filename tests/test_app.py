import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit import config
from streamlit.testing.v1 import AppTest


class AppTests(unittest.TestCase):
    def setUp(self):
        config.get_config_options(force_reparse=True, options_from_flags={'secrets.files': []})

    def test_missing_secrets_and_input_validation(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}), patch('browser_keys.saved_browser_key', return_value=None) as browser_key:
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.text_input), 2)
            at.button[0].click().run()
            self.assertIn('API Key', at.warning[0].value)
            browser_key.return_value = 'test-only'
            at.button[0].click().run()
            self.assertEqual(at.warning[0].value, '영상 URL을 입력해주세요.')

    def test_environment_key_and_result_persistence(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-only'}), patch('video_engine.summarize_video', return_value='검증 요약'):
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.text_input), 2)
            at.text_input[1].input('https://youtu.be/dQw4w9WgXcQ')
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['summary'], '검증 요약')
            at.text_input[1].input('https://youtu.be/abcdefghijk').run()
            self.assertEqual(at.session_state['summary'], '검증 요약')
            self.assertEqual(at.session_state['summary_url'], 'https://youtu.be/dQw4w9WgXcQ')

    def test_saved_browser_key_is_used_and_can_be_removed(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}), patch('browser_keys.saved_browser_key', return_value='test-browser-key') as stored, patch('video_engine.summarize_video', return_value='요약') as summarize:
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
            at.text_input[1].input('https://youtu.be/dQw4w9WgXcQ')
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertEqual(summarize.call_args.args[1], 'test-browser-key')
            stored.return_value = None
            at.run()
            at.button[0].click().run()
            self.assertIn('API Key', at.warning[0].value)
            self.assertEqual(summarize.call_count, 1)

    def test_key_settings_remain_visible_and_manual_input_overrides_server_key(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'server-test-key'}), patch('browser_keys.saved_browser_key', return_value=None) as component, patch('video_engine.summarize_video', return_value='요약') as summarize:
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
            self.assertFalse(at.exception)
            component.assert_called_once()
            self.assertTrue(any('Gemini API 키 설정' in item.label for item in at.expander))
            at.text_input[0].input('personal-test-key')
            at.text_input[1].input('https://youtu.be/dQw4w9WgXcQ')
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertEqual(summarize.call_args.args[1], 'personal-test-key')

    def test_legacy_groq_key_is_not_used(self):
        with patch.dict(os.environ, {'GROQ_API_KEY': 'old-test-key', 'GEMINI_API_KEY': '', 'GOOGLE_API_KEY': ''}), patch('browser_keys.saved_browser_key', return_value=None):
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertIn('Gemini API Key', at.warning[0].value)

    def test_stale_processing_module_stops_before_api_calls(self):
        with patch('video_engine.LOADED_SOURCE_HASH', 'old-source'), patch('video_engine.summarize_video') as summarize:
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
            self.assertFalse(at.exception)
            self.assertIn('실행 중인 처리 모듈이 다릅니다', at.error[0].value)
            self.assertEqual(len(at.button), 0)
            summarize.assert_not_called()

    def test_displayed_versions_and_processing_source_match(self):
        import video_engine
        self.assertTrue(video_engine.is_current_source())
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
        self.assertFalse(at.exception)
        self.assertTrue(any('앱 1.1.1 · 처리 모듈 1.1.1' in item.value for item in at.caption))
