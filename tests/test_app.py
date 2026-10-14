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
        with patch.dict(os.environ, {'GROQ_API_KEY': ''}):
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.text_input), 2)
            at.button[0].click().run()
            self.assertIn('API Key', at.warning[0].value)
            at.text_input[0].input('test-only')
            at.button[0].click().run()
            self.assertEqual(at.warning[0].value, '영상 URL을 입력해주세요.')

    def test_environment_key_and_result_persistence(self):
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test-only'}), patch('media_engine.summarize_video', return_value='검증 요약'):
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.text_input), 1)
            at.text_input[0].input('https://youtu.be/dQw4w9WgXcQ')
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['summary'], '검증 요약')
            at.text_input[0].input('https://youtu.be/abcdefghijk').run()
            self.assertEqual(at.session_state['summary'], '검증 요약')
            self.assertEqual(at.session_state['summary_url'], 'https://youtu.be/dQw4w9WgXcQ')
