"""The SSE progress stream.

This is the regression from v2.4.0 that v2.4.2 had to fix: once jobs started
being launched by /api/download, /api/progress/{job_id} required a "pending"
status that never existed and returned 409 for every job, so the web UI received
no progress at all.

Note on driving the stream: a StreamingResponse's body generator does not run
until it is first iterated, so a test that wants to end the stream must pull one
frame first — otherwise the generator subscribes afterwards and parks on its
queue forever. `subscribe()` does that.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.main as main
from conftest import make_job


async def subscribe(job_id: str):
    """Open the stream and drive it far enough to actually subscribe.

    Returns (stream, pending_first_frame).
    """
    stream = (await main.progress(job_id)).body_iterator
    pending = asyncio.ensure_future(stream.__anext__())
    await asyncio.sleep(0)  # let the generator subscribe and park on its queue
    return stream, pending


async def test_running_job_can_be_subscribed():
    """Regression: subscribing to a running job used to raise 409."""
    job = make_job(job_id="job-running")
    job.status = "running"

    stream, pending = await subscribe("job-running")
    assert len(job.subscribers) == 1

    job.status = "done"
    main._end_subscribers(job)

    assert await pending == "data: DONE:0|\n\n"

    # the queue is released once the generator finishes
    await stream.aclose()
    assert job.subscribers == []


async def test_replays_backlog_then_streams_live_events():
    job = make_job(job_id="job-sse")
    job.status = "running"
    main._publish(job, "TOTAL:2")
    main._publish(job, "TRACK_START:Downloading Track A")

    stream = (await main.progress("job-sse")).body_iterator

    # everything emitted before the client attached is replayed
    assert await stream.__anext__() == "data: TOTAL:2\n\n"
    assert await stream.__anext__() == "data: TRACK_START:Downloading Track A\n\n"

    # then live events, ending with the terminal frame
    job.tracks = ["Track A", "Track B"]
    job.status = "done"
    main._publish(job, "LOG:Done")
    main._end_subscribers(job)

    assert [chunk async for chunk in stream] == [
        "data: LOG:Done\n\n",
        "data: DONE:2|Track A;;Track B\n\n",
    ]


async def test_late_subscriber_gets_the_whole_run():
    job = make_job(job_id="job-late")
    job.status = "done"
    job.tracks = ["A", "B"]
    main._publish(job, "TOTAL:2")
    main._publish(job, "LOG:Done")

    stream = (await main.progress("job-late")).body_iterator
    assert [chunk async for chunk in stream] == [
        "data: TOTAL:2\n\n",
        "data: LOG:Done\n\n",
        "data: DONE:2|A;;B\n\n",
    ]


async def test_failed_job_streams_an_error_frame():
    job = make_job(job_id="job-fail")
    job.status = "failed"
    job.error = "spotdl exited with an error: boom"

    stream = (await main.progress("job-fail")).body_iterator
    assert [chunk async for chunk in stream] == [
        "data: ERROR: spotdl exited with an error: boom\n\n"
    ]


async def test_failed_job_without_a_message_still_reports():
    job = make_job(job_id="job-fail-silent")
    job.status = "failed"

    stream = (await main.progress("job-fail-silent")).body_iterator
    assert [chunk async for chunk in stream] == ["data: ERROR: Download failed.\n\n"]


async def test_progress_does_not_consume_a_download_slot():
    """The job already holds a slot; attaching used to claim a second one."""
    job = make_job(job_id="job-slot")
    job.status = "running"
    main._active_jobs = 1

    stream, pending = await subscribe("job-slot")
    assert main._active_jobs == 1  # attaching claimed nothing

    job.status = "done"
    main._end_subscribers(job)
    await pending

    assert main._active_jobs == 1  # and released nothing
    await stream.aclose()


async def test_subscriber_is_removed_when_the_client_goes_away():
    """A client that disconnects must not leave its queue behind on the job."""
    job = make_job(job_id="job-detach")
    job.status = "running"

    stream = (await main.progress("job-detach")).body_iterator
    pending = asyncio.ensure_future(stream.__anext__())
    await asyncio.sleep(0)
    assert len(job.subscribers) == 1

    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert job.subscribers == []


async def test_unknown_job_is_404():
    with pytest.raises(HTTPException) as exc:
        await main.progress("does-not-exist")
    assert exc.value.status_code == 404
