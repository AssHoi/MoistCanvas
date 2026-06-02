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
    assert "仅支持 PNG / JPG / WebP" not in html
    assert "video/mp4" in html
    assert "video/webm" in html
    assert "video/quicktime" in html
    assert ".mov" in html


def test_external_media_rejection_uses_one_video_aware_toast():
    html = _html()

    assert "function showUnsupportedExternalMediaToast()" in html
    assert html.count("仅支持 ") == 1
    assert html.count("showToast('仅支持 ") == 1

    for fn_name in ("uploadImages", "uploadImagesAtPoint", "addExternalImagesAsPromptRefs"):
        block = _fn(html, fn_name)
        assert "showUnsupportedExternalMediaToast()" in block
        assert "EXTERNAL_MEDIA_FORMATS_LABEL" not in block


def test_drag_and_drop_filters_do_not_use_image_only_regex():
    html = _html()

    canvas_drop = html[
        html.index("// CANVAS FILE DRAG-DROP") :
        html.index("async function uploadImagesAtPoint", html.index("// CANVAS FILE DRAG-DROP"))
    ]
    prompt_drop = html[
        html.index("async function addExternalImagesAsPromptRefs(files)") :
        html.index("// MODEL CATALOG", html.index("async function addExternalImagesAsPromptRefs(files)"))
    ]

    for block in (canvas_drop, prompt_drop):
        assert "isSupportedExternalMedia" in block
        assert "isSupportedExternalImageFile" not in block
        assert "/^image" not in block
        assert "image/" not in block


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
