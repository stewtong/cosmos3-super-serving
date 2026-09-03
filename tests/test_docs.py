import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MARKDOWN = [
    ROOT / "README.md",
    ROOT / "SERVING.md",
    ROOT / "BENCHMARKS.md",
    ROOT / "OBSERVATIONS.md",
    ROOT / "PROVENANCE.md",
    ROOT / "reproduce" / "METHOD.md",
    ROOT / "reproduce" / "REPRODUCE.md",
    ROOT / "results" / "README.md",
]
LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
CJK_OR_FULLWIDTH = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")


class DocumentationTests(unittest.TestCase):
    def test_reader_facing_markdown_declares_register(self):
        for path in MARKDOWN:
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertTrue(first_line.startswith("<!-- register:"), path)

    def test_relative_links_resolve(self):
        for path in MARKDOWN:
            text = path.read_text(encoding="utf-8")
            for destination in LINK.findall(text):
                if destination.startswith(("http://", "https://", "#")):
                    continue
                relative = destination.split("#", 1)[0]
                target = (path.parent / relative).resolve()
                self.assertTrue(target.exists(), f"{path}: missing {destination}")

    def test_public_markdown_is_english_only(self):
        for path in MARKDOWN:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(CJK_OR_FULLWIDTH.search(text), path)


if __name__ == "__main__":
    unittest.main()
