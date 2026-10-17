from app.queue import tasks


def test_worker_entrypoints_exist() -> None:
    assert callable(tasks.buffer_inbound)
    assert callable(tasks.process_wa_id)
    assert tasks.buffer_inbound.__module__ == "app.queue.tasks"
    assert tasks.process_wa_id.__module__ == "app.queue.tasks"
    assert tasks.OUT_OF_SCOPE_REPLY.startswith("Eso no lo puedo responder")
