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


def test_rebinding_resets_old_command_versions_and_thread_selection(tmp_path):
    store = Store(tmp_path)
    store.bind_device("old-device")
    store.put("version", 999)
    store.put("settings", {"thread_id": "old-thread"})
    store.claim("old-command")
    store.bind_device("new-device")
    assert store.get("version", 0) == 0
    assert store.get("settings") is None
    assert store.claim("old-command") is None
    store.close()


def test_upgrade_keeps_legacy_settings_but_explicit_rebind_clears_them(tmp_path):
    store = Store(tmp_path)
    store.put("version", 10)  # v0.1.0 did not save a device_id record
    store.bind_device("same-device")
    assert store.get("version") == 10
    store.bind_device("new-device", reset=True)
    assert store.get("version", 0) == 0
    store.close()
