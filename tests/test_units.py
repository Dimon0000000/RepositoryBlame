import os
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repository_blame.config import load_config, parse_optional_limit
from repository_blame.git_blame import get_language, should_ignore
from repository_blame.svg_renderer import escape, generate_svg, safe_id
from repository_blame.users import normalize_user, parse_github_user_from_email, parse_users


class ConfigTests(unittest.TestCase):
    def test_parse_optional_limit(self):
        self.assertEqual(parse_optional_limit("", default=7), 7)
        self.assertEqual(parse_optional_limit("0", default=7), 0)
        self.assertEqual(parse_optional_limit("12", default=7), 12)
        self.assertIsNone(parse_optional_limit("all", default=7))
        self.assertIsNone(parse_optional_limit("*", default=7))
        self.assertEqual(parse_optional_limit("bad", default=7), 7)

    def test_load_config_combines_default_and_custom_ignore(self):
        config = load_config(
            {
                "INPUT_IGNORE": "generated/**\n*.snap\n",
                "INPUT_WIDTH": "bad",
                "INPUT_MIN_PERCENT": "bad",
            }
        )

        self.assertEqual(config.width, 900)
        self.assertEqual(config.min_percent, 0.8)
        self.assertIn(".git/**", config.ignore_patterns)
        self.assertIn("generated/**", config.ignore_patterns)
        self.assertIn("*.snap", config.ignore_patterns)


class GitBlameHelperTests(unittest.TestCase):
    def test_language_detection(self):
        self.assertEqual(get_language("src/main.py"), ("Python", "#3572A5"))
        self.assertEqual(get_language("Dockerfile"), ("Dockerfile", "#384D54"))
        self.assertIsNone(get_language("README.unknown"))

    def test_should_ignore_path_or_basename(self):
        self.assertTrue(should_ignore("dist/app.js", ["dist/**"]))
        self.assertTrue(should_ignore("src/package-lock.json", ["package-lock.json"]))
        self.assertFalse(should_ignore("src/app.py", ["dist/**"]))


class UserTests(unittest.TestCase):
    def test_parse_users_and_normalize_user(self):
        alias_map, canonical_map = parse_users("Octo=octo@example.com,Octo Cat\n")

        self.assertEqual(normalize_user("Someone", "octo@example.com", alias_map, canonical_map), "Octo")
        self.assertEqual(normalize_user("Octo Cat", "unknown@example.com", alias_map, canonical_map), "Octo")
        self.assertEqual(
            normalize_user("ignored", "123+Octo@users.noreply.github.com", alias_map, canonical_map),
            "Octo",
        )

    def test_parse_github_user_from_email(self):
        self.assertEqual(parse_github_user_from_email("123+name@users.noreply.github.com"), "name")
        self.assertEqual(parse_github_user_from_email("name@users.noreply.github.com"), "name")
        self.assertIsNone(parse_github_user_from_email("name@example.com"))


class SvgRendererTests(unittest.TestCase):
    def test_escape_and_safe_id(self):
        self.assertEqual(escape('<A&B "C">'), "&lt;A&amp;B &quot;C&quot;&gt;")
        self.assertEqual(safe_id("a b/c"), "a-b-c")

    def test_generate_svg_writes_basic_card(self):
        stats = {
            "Octo": {
                "total": 2,
                "langs": {("Python", "#3572A5"): 2},
                "avatar": None,
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "card.svg")
            generate_svg(stats, 2, output, 900, "Code <Stats>", 0.8, 22, 10)
            svg = Path(output).read_text(encoding="utf-8")

        self.assertIn("Code &lt;Stats&gt;", svg)
        self.assertIn("2 non-empty blamed lines", svg)
        self.assertIn("Octo", svg)
        self.assertIn("Python", svg)


class MainEntryTests(unittest.TestCase):
    def test_main_imports_when_loaded_from_file_location(self):
        original_path = list(sys.path)
        try:
            sys.path = [path for path in sys.path if path != str(ROOT / "src")]
            spec = importlib.util.spec_from_file_location("action_main", ROOT / "src" / "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path = original_path

        self.assertTrue(callable(module.main))
        self.assertEqual(module.parse_minor_contributors_limit("all", default=22), None)
        self.assertEqual(module.parse_show_contributors_limit("5", default=10), 5)
        self.assertEqual(module.get_language("main.py")[0], "Python")


if __name__ == "__main__":
    unittest.main()
