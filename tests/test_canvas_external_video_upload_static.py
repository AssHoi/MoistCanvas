"""Static checks for external video upload/drop support on the canvas."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANVAS_HTML = ROOT / "static" / "canvas.html"
MAIN_PY = ROOT / "main.py"


def _html():
    return CANVAS_HTML.read_text(encoding="utf-8")


def _main():
    return MAIN_PY.read_text(encoding="utf-8")


def _fn(source, name):
    needle = f"function {name}"
    start = source.index(needle)
    end = source.find("\nfunction ", start + 1)
    if end < 0:
        end = source.find("\nasync function ", start + 1)
    if end < 0:
        end = len(source)
    return source[start:end]


def test_file_input_and_drop_copy_accept_video_formats():
    html = _html()

    assert 'accept="image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov"' in html
    assert "PNG / JPG / WebP / MP4 / WebM / MOV" in html
    assert "video/mp4" in html
    assert "video/webm" in html
    assert "video/quicktime" in html
    assert ".mov" in html


def test_canvas_uploads_create_video_nodes_for_video_files():
    html = _html()

    upload = _fn(html, "uploadImages")
    at_point = _fn(html, "uploadImagesAtPoint")

    for block in (upload, at_point):
        assert "isVideoUpload(" in block
        assert "createVideoNode(" in block
        assert "createImageNode(" in block


def test_prompt_drop_creates_video_refs_and_inserts_video_chips():
    html = _html()
    helper = html[
        html.index("async function addExternalImagesAsPromptRefs(files)") :
        html.index("(function initPromptDrop()")
    ]

    assert "isVideoUpload(" in helper
    assert "createVideoNode(" in helper
    assert "type: isVideo ? 'video' : 'image'" in helper
    assert "insertAtRef(ref.label)" in helper
    assert "视频" in helper


def test_upload_endpoint_allows_videos_and_returns_kind_metadata():
    source = _main()
    upload = source[source.index("async def upload_ai_reference"): source.index("@app.get(\"/api/providers\")")]

    assert '".mp4"' in upload
    assert '".webm"' in upload
    assert '".mov"' in upload
    assert '"video/mp4"' in upload
    assert '"video/webm"' in upload
    assert '"video/quicktime"' in upload
    assert '"type": kind' in upload
    assert '"kind": kind' in upload
    assert '"mime": mime' in upload
