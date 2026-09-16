from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from creator_service.dashboard_human_results_ui import enhance_human_results_html


def _html() -> str:
    source = Path('src/creator_service/web/dashboard.html').read_text(encoding='utf-8')
    return enhance_human_results_html(source)


def test_human_results_covers_all_known_raw_json_surfaces():
    html = _html()
    assert 'data-yca-human-results' in html
    for element_id in ('auditRaw', 'evidenceRaw', 'keywordResult', 'researchResult', 'strategyResult'):
        assert f"'{element_id}'" in html
    assert '#memoryBox .code' in html
    assert 'Ver dados técnicos (JSON)' in html
    assert 'human-summary' in html
    assert 'human-section' in html


def test_human_results_keeps_raw_json_only_as_optional_technical_details():
    html = _html()
    assert '<details class="human-technical">' in html
    assert '<summary>Ver dados técnicos (JSON)</summary>' in html
    assert "el.classList.remove('code')" in html
    assert "el.classList.add('human-result')" in html


def test_human_results_javascript_is_syntax_valid_when_node_is_available():
    node = shutil.which('node')
    if not node:
        return
    html = _html()
    match = re.search(r'<script data-yca-human-results>(.*?)</script>', html, re.S)
    assert match is not None
    with tempfile.NamedTemporaryFile('w', suffix='.js', encoding='utf-8', delete=False) as handle:
        handle.write(match.group(1))
        path = handle.name
    try:
        result = subprocess.run([node, '--check', path], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
    finally:
        Path(path).unlink(missing_ok=True)
