import pytest


@pytest.fixture(autouse=True)
def celery_runs_tasks_in_process():
    """
    Run Celery tasks synchronously in-process for tests in apps/kafka_events,
    so handlers that call task.delay() do not try to contact a real broker.
    task_eager_propagates makes a failing task raise instead of hiding it.
    Restored after every test.
    """
    from config.celery import app

    previous_eager = app.conf.task_always_eager
    previous_propagates = app.conf.task_eager_propagates
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
    try:
        yield
    finally:
        app.conf.task_always_eager = previous_eager
        app.conf.task_eager_propagates = previous_propagates