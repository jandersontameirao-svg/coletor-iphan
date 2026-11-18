import os
import unittest
from unittest.mock import patch, MagicMock
import ai_classifier


class AIProviderTests(unittest.TestCase):
    def test_anthropic_selected_when_key_present(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'a-key', 'OPENAI_API_KEY': 'o-key'}):
            self.assertEqual(ai_classifier._provider(), 'anthropic')
            self.assertTrue(ai_classifier._model().startswith('claude'))
            self.assertTrue(ai_classifier.available())

    def test_openai_fallback_when_no_anthropic(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': '', 'OPENAI_API_KEY': 'o-key'}):
            self.assertEqual(ai_classifier._provider(), 'openai')
            self.assertFalse(ai_classifier._model().startswith('claude'))

    def test_none_when_no_keys(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': '', 'OPENAI_API_KEY': ''}):
            self.assertIsNone(ai_classifier._provider())
            self.assertFalse(ai_classifier.available())

    def test_complete_routes_to_anthropic_messages_api(self):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured['url'] = url
            captured['headers'] = headers
            captured['json'] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.json = lambda: {'content': [{'type': 'text', 'text': '{"resposta":"ok"}'}]}
            return resp

        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'a-key', 'OPENAI_API_KEY': ''}), \
                patch.object(ai_classifier.httpx, 'post', side_effect=fake_post):
            out = ai_classifier._complete(None, None, [{'role': 'system', 'content': 'SYS'},
                                                       {'role': 'user', 'content': 'U'}])
        self.assertEqual(out, '{"resposta":"ok"}')
        self.assertIn('/v1/messages', captured['url'])
        self.assertEqual(captured['headers']['x-api-key'], 'a-key')
        self.assertEqual(captured['headers']['anthropic-version'], '2023-06-01')
        self.assertEqual(captured['json']['system'], 'SYS')  # system vai separado
        self.assertEqual(captured['json']['messages'][0]['role'], 'user')  # conversa começa com user


if __name__ == '__main__':
    unittest.main()
