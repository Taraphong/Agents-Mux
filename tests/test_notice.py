"""Static unit regressions for PR #26's notice markup and positioning.

Run with ``python -m unittest discover -s tests -p 'test_notice.py'``.
The script syntax regression additionally uses Node.js when available.
These tests check template contracts; they do not replace browser layout tests.
"""

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "index.html"
VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)


class Element:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []
        self.text = ""

    @property
    def classes(self):
        return self.attrs.get("class", "").split()


class TemplateParser(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.elements = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(element)
        self.elements.append(element)
        if tag not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].text += data


def css_rules(source, media=()):
    """Read balanced CSS blocks, retaining enclosing at-rules and source order.

    Only declarations are inspected, never computed browser geometry. Comments
    are removed by the caller so braces in comments cannot affect nesting.
    """
    position = 0
    while (opening := source.find("{", position)) != -1:
        selector = source[position:opening].strip()
        depth = 1
        closing = opening + 1
        while closing < len(source) and depth:
            depth += (source[closing] == "{") - (source[closing] == "}")
            closing += 1
        if depth:
            raise ValueError("Unbalanced CSS block")
        body = source[opening + 1:closing - 1]
        if selector.startswith("@"):
            yield from css_rules(body, (*media, selector))
        else:
            declarations = {}
            for declaration in body.split(";"):
                if ":" in declaration:
                    name, value = declaration.split(":", 1)
                    declarations[name.strip()] = value.strip()
            for individual in selector.split(","):
                yield media, individual.strip(), declarations
        position = closing


class NoticeTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = TemplateParser(TEMPLATE.read_text(encoding="utf-8"))
        styles = "\n".join(
            node.text for node in cls.document.elements if node.tag == "style"
        )
        cls.rules = list(css_rules(re.sub(r"/\*.*?\*/", "", styles, flags=re.S)))

    def notice(self):
        matches = [
            node for node in self.document.elements
            if node.attrs.get("id") == "notice"
        ]
        self.assertEqual(len(matches), 1, "Notice ID must be unique")
        return matches[0]

    def declarations(self, selector, media=()):
        result = {}
        for context, candidate, declarations in self.rules:
            if context == media and candidate == selector:
                result.update(declarations)
        self.assertTrue(result, f"Missing CSS rule: {media} {selector}")
        return result

    def test_exactly_one_shared_notice(self):
        self.assertIn("notice", self.notice().classes)

    def test_notice_is_direct_child_of_layout(self):
        self.assertIn("layout", self.notice().parent.classes)

    def test_notice_is_outside_all_switchable_views_and_scrolling_content(self):
        ancestor = self.notice().parent
        while ancestor is not None:
            with self.subTest(tag=ancestor.tag, attrs=ancestor.attrs):
                self.assertNotIn("view", ancestor.classes)
                self.assertNotIn("content", ancestor.classes)
            ancestor = ancestor.parent

    def test_notice_follows_header_and_precedes_content(self):
        notice = self.notice()
        siblings = notice.parent.children
        index = siblings.index(notice)
        self.assertGreater(index, 0)
        self.assertLess(index + 1, len(siblings))
        self.assertEqual(siblings[index - 1].tag, "header")
        self.assertIn("content", siblings[index + 1].classes)

    def test_notice_is_a_polite_live_status_region(self):
        self.assertEqual(self.notice().attrs.get("role"), "status")
        self.assertEqual(self.notice().attrs.get("aria-live"), "polite")

    def test_notice_starts_empty_and_hidden(self):
        self.assertEqual(self.notice().text.strip(), "")
        self.assertEqual(self.declarations(".notice")["display"], "none")
        self.assertNotIn("style", self.notice().attrs)

    def test_mobile_notice_is_viewport_overlay(self):
        notice = self.declarations(".notice")
        self.assertEqual(notice["position"], "fixed")
        self.assertEqual(notice["top"], "80px")
        self.assertEqual(notice["left"], "50%")
        self.assertEqual(notice["transform"], "translateX(-50%)")

    def test_overlay_does_not_intercept_clicks_or_add_bottom_spacing(self):
        notice = self.declarations(".notice")
        self.assertEqual(notice["pointer-events"], "none")
        self.assertEqual(notice["margin-bottom"], "0")
        self.assertGreater(int(notice["z-index"]), 0)
        self.assertNotEqual(notice["box-shadow"], "none")

    def test_desktop_overlay_has_layout_positioning_context(self):
        self.assertEqual(self.declarations(".layout")["position"], "relative")
        desktop = self.declarations(".notice", ("@media (min-width: 701px)",))
        self.assertEqual(desktop["position"], "absolute")

    def test_both_layout_modes_limit_width_and_reserve_screen_gutters(self):
        for media in ((), ("@media (min-width: 701px)",)):
            with self.subTest(media=media):
                self.assertEqual(
                    self.declarations(".notice", media)["width"],
                    "min(560px, calc(100% - 32px))",
                )

    def test_positioning_has_no_conflicting_later_notice_overrides(self):
        # Theme and mobile overrides must preserve the shared overlay contract.
        layout_properties = {"position", "left", "top", "transform", "width"}
        for media, selector, declarations in self.rules:
            if ".notice" not in selector:
                continue
            if selector == ".notice" and media in (
                (), ("@media (min-width: 701px)",)
            ):
                continue
            with self.subTest(media=media, selector=selector):
                self.assertFalse(layout_properties.intersection(declarations))

    @unittest.skipUnless(shutil.which("node"), "Node.js required for syntax check")
    def test_inline_javascript_parses_after_chat_function_delimiter_fix(self):
        scripts = [
            node.text for node in self.document.elements
            if node.tag == "script" and "src" not in node.attrs
        ]
        self.assertTrue(scripts, "Expected application inline JavaScript")
        for index, script in enumerate(scripts):
            with self.subTest(script=index):
                result = subprocess.run(
                    [shutil.which("node"), "--check"],
                    input=script, text=True, capture_output=True,
                    timeout=10, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
