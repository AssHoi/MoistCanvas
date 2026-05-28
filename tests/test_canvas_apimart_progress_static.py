from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
CANVAS = ROOT / "static" / "canvas.html"


def read(path):
    return path.read_text(encoding="utf-8")


def test_request_timeout_default_is_300():
    main = read(MAIN)
    assert 'AI_REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "300"))' in main


def test_apimart_job_status_endpoint_and_updates_exist():
    main = read(MAIN)
    assert 'APIMART_JOB_STATUS' in main
    assert '@app.get("/api/apimart-job/{client_job_id}")' in main
    assert 'language=zh' in main
    assert '_set_apimart_job_status(client_job_id' in main
    assert '"actualTime": task_data.get("actual_time")' in main
    assert '"estimatedTime": task_data.get("estimated_time")' in main
    assert '"cost": task_data.get("cost")' in main
    assert '"pollCount": poll_count' in main
    assert '"elapsedSeconds": elapsed' in main
    assert "timeout=AI_REQUEST_TIMEOUT, client_job_id=client_job_id" in main
    assert '"code": "apimart_task_timeout"' in main
    assert '"task_info": _get_apimart_job_status(client_job_id)' in main


def test_frontend_polls_and_persists_task_info():
    html = read(CANVAS)
    assert '_startApimartJobPolling(asstMsgId, clientJobId)' in html
    assert "setTimeout(poll, 10000)" in html
    assert "'X-Client-Job-Id': clientJobId" in html
    assert "pollCount:" in html
    assert "elapsedSeconds:" in html
    assert "taskInfo:  d.task_info || d.taskInfo || null" in html
    assert "info.taskInfo || data.task_info || null" in html
    assert "taskInfo:" in html
    assert "m.taskInfo && typeof m.taskInfo === 'object'" in html


def test_frontend_renders_progress_and_done_cost():
    html = read(CANVAS)
    assert "function _taskStatusText(taskInfo, isDone)" in html
    assert "function _taskDoneText(taskInfo)" in html
    assert "耗时 " in html
    assert "费用 " in html
    assert "已等待 " in html
    assert "次查询" in html
    assert "_appendTaskInfoLine(wrap, m.taskInfo, false)" in html
    assert "_appendTaskInfoLine(wrap, m.taskInfo, true)" in html


if __name__ == "__main__":
    test_request_timeout_default_is_300()
    test_apimart_job_status_endpoint_and_updates_exist()
    test_frontend_polls_and_persists_task_info()
    test_frontend_renders_progress_and_done_cost()
    print("OK")
