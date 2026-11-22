import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MiniAppMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.pages = {}
        self.handlers = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        element_id = attrs.get("id")
        if element_id:
            self.ids.append(element_id)
            self.pages[element_id] = (tag, set(attrs.get("class", "").split()))
        if attrs.get("onclick"):
            self.handlers.append(attrs["onclick"])


def test_every_inline_click_handler_resolves_to_a_javascript_function():
    html = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")
    parser = MiniAppMarkup()
    parser.feed(html)

    declared = set(re.findall(
        r"(?:async\\s+)?function\\s+([A-Za-z_$][\\w$]*)\\s*\\(", html
    ))
    declared.update(re.findall(
        r"(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*(?:async\\s*)?\\([^)]*\\)\\s*=>",
        html,
    ))

    referenced = set()
    for handler in parser.handlers:
        referenced.update(re.findall(
            r"(?:^|[;{]\\s*)([A-Za-z_$][\\w$]*)\\s*\\(", handler
        ))

    ignored = {"if", "for", "while", "switch"}
    missing = sorted(referenced - declared - ignored)
    assert not missing, f"Inline click handlers reference missing functions: {missing}"


def test_every_open_page_target_exists_as_a_page_section():
    html = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")
    parser = MiniAppMarkup()
    parser.feed(html)

    targets = set(re.findall(r"openPage\\(\\s*['\\\"]([^'\\\"]+)['\\\"]\\s*\\)", html))
    missing = sorted(
        target for target in targets
        if target not in parser.pages
        or parser.pages[target][0] != "section"
        or "page" not in parser.pages[target][1]
    )
    assert not missing, f"openPage() targets missing/non-page sections: {missing}"


def test_frontend_api_calls_are_registered_by_the_backend():
    html = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")
    backend = (ROOT / "main.py").read_text(encoding="utf-8")

    frontend_routes = set(re.findall(r"fetch\\(\\s*['\\\"](/api/[^'\\\"]+)['\\\"]", html))
    backend_routes = set(re.findall(
        r"app\\.router\\.add_post\\(\\s*['\\\"](/api/[^'\\\"]+)['\\\"]",
        backend,
    ))
    missing = sorted(frontend_routes - backend_routes)
    assert not missing, f"Mini App calls API routes not registered by backend: {missing}"


def test_mini_app_element_ids_are_unique():
    html = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")
    parser = MiniAppMarkup()
    parser.feed(html)
    duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    assert not duplicates, f"Duplicate HTML element IDs: {duplicates}"
