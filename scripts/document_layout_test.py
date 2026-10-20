import unittest

from document_layout import normalize_layout


def paragraph(text, emphasis=False):
    tokens = [{"type": "text", "text": text}]
    return {"type": "paragraph", "tokens": [{"type": "em", "tokens": tokens}] if emphasis else tokens}


class LayoutTests(unittest.TestCase):
    def test_title_cover_and_caption_changes_preserve_body(self):
        ast = [
            {"type": "heading", "depth": 1, "tokens": [{"type": "text", "text": "旧标题"}]},
            paragraph("完整原文。"),
            {"type": "paragraph", "tokens": [{"type": "image", "href": "imgs/00-cover-main.png"}]},
            paragraph("封面说明。", True),
            {"type": "paragraph", "tokens": [{"type": "image", "href": "imgs/01-detail.png"}]},
            paragraph("图9 内容解释。"),
        ]
        result, changes = normalize_layout(ast, "任务名称")
        self.assertEqual(result[0]["tokens"][0]["text"], "任务名称")
        self.assertEqual(result[1]["tokens"][0]["href"], "imgs/00-cover-main.png")
        self.assertEqual(result[2]["text"], "封面说明")
        self.assertEqual(result[3]["tokens"][0]["text"], "完整原文。")
        self.assertEqual(result[5]["text"], "图1 内容解释")
        self.assertEqual(ast[0]["tokens"][0]["text"], "旧标题")
        self.assertTrue(changes)

    def test_decimal_period_inside_caption_remains(self):
        ast = [
            {"type": "paragraph", "tokens": [{"type": "image", "href": "01-image.png"}]},
            paragraph("图1 3.5 V下的状态."),
        ]
        result, _ = normalize_layout(ast, "任务名称")
        self.assertEqual(result[-1]["text"], "图1 3.5 V下的状态")

    def test_plain_body_emphasis_is_preserved(self):
        result, _ = normalize_layout([paragraph("正文强调。", True)], "任务名称")
        self.assertEqual(result[1]["tokens"][0]["type"], "em")
        self.assertEqual(result[1]["tokens"][0]["tokens"][0]["text"], "正文强调。")

    def test_section_numbers_follow_depth_reset_and_do_not_accumulate(self):
        ast = [{"type": "heading", "depth": depth, "tokens": [{"type": "text", "text": title}]}
               for depth, title in ((1, "任务名称"), (2, "原理"), (3, "方法"), (3, "条件"),
                                    (4, "边界"), (2, "应用"), (3, "验证"))]
        result, _ = normalize_layout(ast, "任务名称", number_sections=True)
        expected = ["任务名称", "1 原理", "1.1 方法", "1.2 条件", "1.2.1 边界", "2 应用", "2.1 验证"]
        self.assertEqual(["".join(t["text"] for t in b["tokens"]) for b in result], expected)
        again, _ = normalize_layout(result, "任务名称", number_sections=True)
        self.assertEqual(["".join(t["text"] for t in b["tokens"]) for b in again], expected)


if __name__ == "__main__":
    unittest.main()
