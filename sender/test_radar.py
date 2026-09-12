"""오프라인 회귀 테스트. 기상청 요청·저장소 업로드·알림 발송 없음."""
import io
import struct
import time
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

import requests
from PIL import Image
import radar


class RadarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = struct.pack('<hh', 2305, 2881) + bytes(2305 * 2881 * 2)
        buf = io.BytesIO()
        Image.new('RGB', (600, 770)).save(buf, format='PNG')
        cls.png = buf.getvalue()

    def setUp(self):
        radar._started = time.monotonic()
        radar._qpf_cache.clear()

    def response(self, content, status=200):
        res = MagicMock()
        res.__enter__.return_value = res
        res.content = content
        if status != 200:
            res.raise_for_status.side_effect = requests.HTTPError(
                response=type('Response', (), {'status_code': status})())
        return res

    def test_complete_grid(self):
        radar.validate_radar(self.raw)

    def test_bad_grid(self):
        for raw in (b'', b'<html>error</html>', self.raw[:-2], self.raw + b'junk'):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                radar.validate_radar(raw)

    def test_complete_png(self):
        radar.validate_png(self.png, 'HB')

    def test_wrong_png_dimensions(self):
        buf = io.BytesIO()
        Image.new('RGB', (600, 600)).save(buf, format='PNG')
        with self.assertRaises(ValueError):
            radar.validate_png(buf.getvalue(), 'HB')

    def test_render_rejects_incomplete_grid(self):
        with self.assertRaises(ValueError):
            radar.render(self.raw[:-2], 36.5, 127.8)

    def test_workflow_does_not_require_sender_success(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    '.github/workflows/radar.yml').read_text(encoding='utf-8')
        self.assertIn('types: [completed]', workflow)
        self.assertNotIn("conclusion == 'success'", workflow)

    @patch('radar.time.sleep')
    @patch('radar.requests.get')
    def test_http_500_retries(self, get, sleep):
        get.side_effect = [self.response(b'error', 500), self.response(self.png)]
        self.assertEqual(radar._qpf_image(datetime.now(), 60, 'HB'), self.png)
        self.assertEqual(get.call_count, 2)

    def test_truncated_png(self):
        with self.assertRaises((OSError, ValueError, SyntaxError)):
            radar.validate_png(self.png[:len(self.png)//2], 'HB')

    @patch('radar.time.sleep')
    @patch('radar.requests.get')
    def test_truncated_grid_retries_same_timestamp(self, get, sleep):
        get.side_effect = [self.response(self.raw[:-20]), self.response(self.raw)]
        raw, stamp = radar.fetch_radar(tm=datetime(2026, 9, 12, 18))
        self.assertEqual(raw, self.raw)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs['params'],
                         get.call_args_list[1].kwargs['params'])

    @patch('radar.time.sleep')
    @patch('radar.requests.get')
    def test_timeout_retries(self, get, sleep):
        get.side_effect = [requests.ConnectTimeout(), self.response(self.raw)]
        self.assertEqual(radar.fetch_radar(tm=datetime.now())[0], self.raw)

    @patch('radar.requests.get')
    def test_http_auth_not_accepted(self, get):
        get.return_value = self.response(self.raw, 403)
        self.assertIsNone(radar.fetch_radar(tm=datetime.now())[0])
        self.assertEqual(get.call_count, 1)

    @patch('radar.time.sleep')
    @patch('radar.requests.get')
    def test_invalid_png_retry_and_success_cache(self, get, sleep):
        get.side_effect = [self.response(self.png[:40]), self.response(self.png)]
        base = datetime.now()
        self.assertEqual(radar._qpf_image(base, 30, 'HB'), self.png)
        self.assertEqual(radar._qpf_image(base, 30, 'HB'), self.png)
        self.assertEqual(get.call_count, 2)

    @patch('radar.requests.get')
    def test_deadline_no_request(self, get):
        radar._started -= radar.DEADLINE_SEC + 1
        self.assertIsNone(radar._qpf_image(datetime.now(), 30))
        get.assert_not_called()

    @patch('radar.upload')
    @patch('radar._qpf_overlay', return_value=(None, None))
    @patch('radar._qpf_image', return_value=b'base available')
    def test_empty_forecast_preserves_previous(self, image, overlay, upload):
        self.assertIsNone(radar.build_forecast(36.5, 127.8, 'national'))
        upload.assert_not_called()

    @patch('radar.upload', return_value=None)
    @patch('radar.render')
    def test_failed_image_upload_does_not_replace_metadata(self, render, upload):
        render.return_value = (Image.new('RGBA', (2, 2)), {}, {'rain_cells': 0})
        self.assertIsNone(radar.build_for(1, 2, 36.5, 127.8, 'test', raw=b'x'))
        self.assertEqual(upload.call_count, 1)


if __name__ == '__main__':
    unittest.main()
