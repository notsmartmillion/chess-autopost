"""The written commentary IS the product; templates must never ship as it.

An expired Anthropic key produced a full fifty-minute render of template
prose, titled "Korchnoi vs Carlsen - Smartfish Masters - 2004", which then
uploaded itself. The audit reported "narration is 'template', not LLM" and
nothing was listening, because the script section was advisory.
"""

import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[3] / "services" / "orchestrator"
sys.path.insert(0, str(ORCH))


def test_the_build_refuses_template_prose_when_it_asked_for_writing():
    src = (ORCH / "build_video.py").read_text(encoding="utf-8")
    assert "allow_template_narration" in src, "no escape hatch, so no guard"
    assert 'get("narration") != "llm"' in src, "the guard does not check the verdict"
    # And it must stop BEFORE the render, like the voice guard does.
    guard = src.index('get("narration") != "llm"')
    render = src.index("def render(")
    body = src[guard:guard + 900]
    assert "return 5" in body, "the guard does not stop the build"


def test_the_upload_gate_blocks_a_template_script():
    """Defence in depth: even a build that skipped the guard must not post."""
    src = (ORCH / "flow.py").read_text(encoding="utf-8")
    blocking = src.split('r.get("section") in (')[1].split(")")[0]
    for section in ("voice", "claims", "arrows", "script"):
        assert f'"{section}"' in blocking, f"{section} errors do not block uploads"


def test_the_voice_guard_is_still_there():
    """The narration guard was modelled on it; neither should drift away."""
    src = (ORCH / "build_video.py").read_text(encoding="utf-8")
    assert "allow_fallback_voice" in src
    assert "VOICE_BACKENDS" in src
