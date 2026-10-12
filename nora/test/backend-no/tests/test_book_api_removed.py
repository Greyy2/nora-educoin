# Đã chuyển khỏi test/ (P17 T1-B5c): endpoint dựng sổ (book_build) và xuất bản (publish) đã gỡ cùng kho tối ưu; bản gốc ở tag pre-p17-research.
def test_build_params_and_whitelist(client):
    r = client.post("/api/studio/book/build", json={"only": ["trend_long"], "n": 6})
    assert r.status_code == 200
    kind, p = launched(FakePopen.calls[0])
    assert kind == "book_build" and p["only"] == ["trend_long"] and p["n"] == 6
    out = p["out"]           # build luôn ghi vào thư mục job, không đụng nora/data/alphas
    job_id = os.path.basename(os.path.dirname(out))
    assert out == os.path.join(batch_jobs.jobs_root(), job_id, "alphas") and out != os.path.join(batch_jobs.NORA_DIR, "data", "alphas")
    assert client.post("/api/studio/book/build", json={"only": ["x"]}).status_code == 422
    assert client.post("/api/studio/book/build", json={"n": 0}).status_code == 422
    # tầng batch_jobs không tin router: loại job lạ / tham số lạ / giá trị không ghi được JSON bị chặn
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.launch("shell", {"c": "id"})
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.launch("book_build", {"out": "/etc"})
    with pytest.raises(batch_jobs.JobError):
        batch_jobs.launch("book_build", {"n": float("nan")})
    with pytest.raises(batch_jobs.JobError):
        process_routes.build_job("rm", {})


def _built_job(state="done", book=True, testnet=False, name=None, kind="book_build"):
    jid, d = _fake_job(kind=kind, pid=os.getpid() if state == "running" else None, state=state, name=name, log="x\n")
    if book:
        os.makedirs(os.path.join(d, "alphas", "testnet"), exist_ok=True)
        open(os.path.join(d, "alphas", "book.json"), "w").write(json.dumps({"status": "READY_FOR_TESTNET" if testnet else "HOLDOUT_FAILED",
                                                                           "holdout_pass": testnet, "generated_at": 7,
                                                                           "strategies": [{"id": "trend_long"}]}))
        if testnet:
            open(os.path.join(d, "alphas", "testnet", "book.json"), "w").write(json.dumps({"mode": "testnet"}))
        else:
            os.rmdir(os.path.join(d, "alphas", "testnet"))
    return jid


def test_publish_copies_book_and_testnet_and_cleans_stale(client, tmp_path, monkeypatch):
    dest = tmp_path / "published"
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(dest))
    monkeypatch.delenv("NORA_BOOK_PATH")
    j1 = _built_job(testnet=True, name="20260101_000001_aaaaaa")
    r = client.post("/api/studio/book/publish", json={"job_id": j1})
    assert r.status_code == 200, r.text
    assert r.json()["published"] and r.json()["status"] == "READY_FOR_TESTNET" and r.json()["strategies"] == ["trend_long"]
    assert json.loads((dest / "book.json").read_text())["generated_at"] == 7
    assert json.loads((dest / "testnet" / "book.json").read_text()) == {"mode": "testnet"}
    # sổ trượt holdout (không có testnet/book.json) -> testnet cũ ở đích bị xoá
    j2 = _built_job(testnet=False, name="20260101_000002_bbbbbb")
    r = client.post("/api/studio/book/publish", json={"job_id": j2})
    assert r.status_code == 200 and r.json()["testnet_removed"] is True
    assert json.loads((dest / "book.json").read_text())["status"] == "HOLDOUT_FAILED"
    assert not (dest / "testnet" / "book.json").exists()
    assert not list(dest.rglob("*.tmp"))


def test_publish_errors(client, tmp_path, monkeypatch):
    dest = tmp_path / "published"
    monkeypatch.setenv("NORA_ALPHAS_DIR", str(dest))
    monkeypatch.delenv("NORA_BOOK_PATH")
    no_book = _built_job(book=False, name="20260101_000003_cccccc")
    assert client.post("/api/studio/book/publish", json={"job_id": no_book}).status_code == 409      # job xong nhưng không có book.json
    running = _built_job(state="running", name="20260101_000004_dddddd")
    assert client.post("/api/studio/book/publish", json={"job_id": running}).status_code == 409
    other = _built_job(kind="book_wfa", name="20260101_000005_eeeeee")
    assert client.post("/api/studio/book/publish", json={"job_id": other}).status_code == 422
    assert client.post("/api/studio/book/publish", json={"job_id": "20260101_000000_ffffff"}).status_code == 404
    assert client.post("/api/studio/book/publish", json={"job_id": "../../etc"}).status_code == 422
    assert not dest.exists()
