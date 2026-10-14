from anybot.storage import Store


def test_claim_survives_close_and_preserves_final_result(tmp_path):
    store = Store(tmp_path)
    assert store.claim("new-session") is None
    store.close()
    other = Store(tmp_path)
    assert other.claim("new-session")["ok"] is False
    other.complete("new-session", {"ok": True, "thread_id": "one"})
    assert other.claim("new-session") == {"ok": True, "thread_id": "one"}
    other.close()
