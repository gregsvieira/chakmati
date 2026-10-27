import pytest

from chakmati.approvals import (
    Action,
    ActionExpired,
    ActionNotPending,
    ActionStore,
    ApprovalService,
)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class SyncService(ApprovalService):
    prefix = "sync."

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.ran = []
        self.fail = False

    def _execute(self, action: Action) -> str:
        if self.fail:
            raise RuntimeError("nope")
        self.ran.append(action.id)
        return "done " + action.payload["x"]


class AsyncService(ApprovalService):
    prefix = "async."

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.ran = []
        self.blocked = None

    async def _aprecheck(self, action: Action) -> None:
        if self.blocked:
            raise PermissionError(self.blocked)

    async def _aexecute(self, action: Action) -> str:
        self.ran.append(action.id)
        return "adone " + action.payload["x"]


@pytest.fixture
def parts():
    store, clock = ActionStore(":memory:"), Clock()
    return SyncService(store, 3600, clock), AsyncService(store, 3600, clock), store, clock


def test_services_only_see_and_own_their_own_prefix(parts):
    sync, asy, store, _ = parts
    a = sync._propose("sync.thing", "S", {"x": "1"})
    b = asy._propose("async.thing", "A", {"x": "2"})
    assert [x.id for x in sync.pending()] == [a.id] and [x.id for x in asy.pending()] == [b.id]
    assert sync.owns(a.id) and not sync.owns(b.id) and asy.owns(b.id)
    with pytest.raises(KeyError):
        sync.approve(b.id)  # another integration's action is "not found", never executed


def test_sync_approve_runs_once_and_records_failures(parts):
    sync, _, store, _ = parts
    a = sync._propose("sync.thing", "S", {"x": "1"})
    assert sync.approve(a.id).result == "done 1" and sync.ran == [a.id]
    with pytest.raises(ActionNotPending):
        sync.approve(a.id)
    sync.fail = True
    f = sync.approve(sync._propose("sync.thing", "S", {"x": "2"}).id)
    assert f.status == "failed" and "nope" in f.error


async def test_async_approve_uses_the_async_hook_and_the_same_rules(parts):
    _, asy, _, clock = parts
    a = asy._propose("async.thing", "A", {"x": "7"})
    done = await asy.aapprove(a.id)
    assert done.status == "executed" and done.result == "adone 7" and asy.ran == [a.id]
    with pytest.raises(ActionNotPending):
        await asy.aapprove(a.id)
    old = asy._propose("async.thing", "A", {"x": "8"})
    clock.t += 3601
    with pytest.raises(ActionExpired):
        await asy.aapprove(old.id)


async def test_precheck_can_refuse_without_consuming_the_action(parts):
    _, asy, store, _ = parts
    a = asy._propose("async.thing", "A", {"x": "1"})
    asy.blocked = "limit reached"
    with pytest.raises(PermissionError):
        await asy.aapprove(a.id)
    assert store.get(a.id).status == "pending"  # still pending: the user can approve later
    asy.blocked = None
    assert (await asy.aapprove(a.id)).status == "executed"


async def test_async_approve_defaults_to_the_sync_executor_in_a_thread(parts):
    sync, _, _, _ = parts
    a = sync._propose("sync.thing", "S", {"x": "9"})
    assert (await sync.aapprove(a.id)).result == "done 9"
