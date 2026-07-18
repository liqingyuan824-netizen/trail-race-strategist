from __future__ import annotations

import unittest

from race_sources.wechat import _image_urls, _verification_required, _visible_text


ARTICLE = """<html><body><div id='js_content'><p>赛道资料</p><img data-src='https://mmbiz.qpic.cn/a.png'><img src='https://mmbiz.qpic.cn/b.png'></div></body></html>"""


class WeChatCaptureParsingTests(unittest.TestCase):
    def test_extracts_visible_text_and_original_image_urls(self):
        self.assertEqual(_visible_text(ARTICLE), "赛道资料")
        self.assertEqual(_image_urls(ARTICLE), ["https://mmbiz.qpic.cn/a.png", "https://mmbiz.qpic.cn/b.png"])

    def test_verification_detection_uses_final_url_or_page_content(self):
        self.assertTrue(_verification_required(final_url="https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha", html=""))
        self.assertTrue(_verification_required(final_url="https://mp.weixin.qq.com/s/example", html="请完成验证"))
        self.assertFalse(_verification_required(final_url="https://mp.weixin.qq.com/s/example", html=ARTICLE))


if __name__ == "__main__":
    unittest.main()
