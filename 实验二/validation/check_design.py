"""Executable DESIGN MODEL, not a database or application implementation.

Enumerates lock/commit orders and checks business invariants, rollback, replay,
deadline boundaries and stale requests. PostgreSQL's real transaction, crash,
timeout and isolation behavior must be tested in later integration work.
Run from any directory: python <absolute path to this file>
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from itertools import permutations
from pathlib import Path
import io
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400
ACTIVE = {'PENDING', 'CONFIRMED'}
FAILPOINTS = ('after_reservation', 'after_product', 'after_result',
              'after_audit', 'before_commit')


@dataclass(frozen=True)
class Command:
    actor: str
    action: str
    key: str
    version: int | None = 0
    product: str = 'P'
    reservation: str | None = None
    place: str = 'library'
    delivery: int = 1000
    reason: str = ''

    @property
    def K(self):
        return self.actor, self.action, self.key

    @property
    def digest(self):
        # An exact tuple stands in for canonical serialization + digest.
        # Server execution time is deliberately not part of request content.
        return (self.product, self.reservation, self.version,
                self.place, self.delivery, self.reason)


@dataclass
class Reply:
    code: str
    outcome: str = ''
    reservation: str | None = None
    current: str | None = None


class Model:
    def __init__(self):
        self.products = {'P': dict(status='PUBLISHED', seller='S', version=0,
                                   price=100, published=10)}
        self.reservations = {}
        self.results = {}
        self.audit = []
        self.key_locks = set()
        self.product_locks = set()

    def invariant(self):
        for product, p in self.products.items():
            records = [r for r in self.reservations.values() if r['product'] == product]
            active = [r for r in records if r['status'] in ACTIVE]
            completed = [r for r in records if r['status'] == 'COMPLETED']
            assert len(active) <= 1, 'I1: duplicate active reservation'
            assert (p['status'] == 'RESERVED') == (len(active) == 1), 'I2'
            assert len(completed) <= 1, 'I3: duplicate completed reservation'
            assert (p['status'] == 'SOLD') == (len(completed) == 1), 'I3'
            for r in records:
                assert r['buyer'] != p['seller'], 'I4: self purchase'
                assert (r['status'] == 'COMPLETED') == (r['completed'] is not None), 'I5'
        for key, result in self.results.items():
            changes = [a for a in self.audit if a[0] == key and a[1] == 'CHANGE']
            assert len(changes) == (1 if result['outcome'] == 'SUCCESS' else 0), 'I6'

    def begin(self, command, *, readable=True):
        if not readable:
            return Reply('FORBIDDEN')
        if command.K in self.key_locks:
            return Reply('WAIT_KEY')
        self.key_locks.add(command.K)
        old = self.results.get(command.K)
        if old:
            self.key_locks.remove(command.K)
            if old['digest'] != command.digest:
                return Reply('KEY_CONFLICT')
            rid = old['reservation']
            current = self.reservations[rid]['status'] if rid else self.products[command.product]['status']
            return Reply('REPLAY', old['outcome'], rid, current)
        return Transaction(self, command)

    def run(self, command, *, now=100, fail=None, readable=True):
        for _ in range(3):
            tx = self.begin(command, readable=readable)
            if isinstance(tx, Reply):
                return tx
            if not tx.lock_product():
                tx.rollback()
                return Reply('WAIT_PRODUCT')
            active = next(((rid, r) for rid, r in tx.records.items() if r['status'] in ACTIVE), None)
            if (command.action in {'create', 'accept'} and active
                    and active[1]['status'] == 'PENDING'
                    and now >= min(active[1]['created'] + DAY, active[1]['delivery'])):
                rid = active[0]
                tx.rollback()
                self.run(Command('SYSTEM', 'expire', rid, None,
                                 command.product, rid), now=now)
                continue
            tx.apply(now)
            return tx.commit(fail=fail)
        return Reply('RETRY')


class Transaction:
    def __init__(self, model, command):
        self.model, self.command = model, command
        self.locked = False
        self.outcome = 'REJECTED'
        self.rid = command.reservation
        self.noop = False

    def lock_product(self):
        if self.command.product in self.model.product_locks:
            return False
        self.model.product_locks.add(self.command.product)
        self.locked = True
        self.product = deepcopy(self.model.products[self.command.product])
        self.records = {rid: deepcopy(r) for rid, r in self.model.reservations.items()
                        if r['product'] == self.command.product}
        self.before = deepcopy((self.product, self.records))
        return True

    def apply(self, now):
        c, p = self.command, self.product
        active = [(rid, r) for rid, r in self.records.items() if r['status'] in ACTIVE]
        r = self.records.get(c.reservation)
        if c.action != 'expire' and c.version != p['version']:
            return
        ok = False
        if c.action == 'create':
            ok = (p['status'] == 'PUBLISHED' and not active and c.actor != p['seller']
                  and 2 <= len(c.place) <= 100 and now < c.delivery <= now + 30 * DAY)
            if ok:
                self.rid = f'{c.actor}:{c.key}'
                self.records[self.rid] = dict(product=c.product, buyer=c.actor,
                    status='PENDING', price=p['price'], place=c.place,
                    delivery=c.delivery, created=now, completed=None, closure=None)
                p['status'] = 'RESERVED'
        elif c.action == 'takeDown':
            ok = c.actor == p['seller'] and p['status'] == 'PUBLISHED' and not active
            if ok:
                p['status'] = 'OFF_SHELF'
        elif c.action == 'ban':
            ok = c.actor == 'ADMIN' and bool(c.reason) and p['status'] in {
                'REVIEWING', 'REJECTED', 'PUBLISHED', 'RESERVED', 'OFF_SHELF'}
            if ok:
                if active:
                    rid, target = active[0]
                    target.update(status='CANCELLED', closure=('platform', c.reason, now))
                p['status'] = 'BANNED'
        elif r and active and active[0][0] == c.reservation and p['status'] == 'RESERVED':
            pending, confirmed = r['status'] == 'PENDING', r['status'] == 'CONFIRMED'
            if c.action == 'accept':
                ok = c.actor == p['seller'] and pending and now < min(r['created'] + DAY, r['delivery'])
                if ok:
                    r['status'] = 'CONFIRMED'
            elif c.action == 'reject':
                ok = c.actor == p['seller'] and pending and bool(c.reason)
                if ok:
                    r.update(status='REJECTED', closure=('seller', c.reason, now))
                    p['status'] = 'PUBLISHED'
            elif c.action == 'cancel':
                ok = ((pending and c.actor == r['buyer']) or
                      (confirmed and c.actor in {r['buyer'], p['seller']} and bool(c.reason)))
                if ok:
                    r.update(status='CANCELLED', closure=(c.actor, c.reason, now))
                    p['status'] = 'PUBLISHED'
            elif c.action == 'expire':
                ok = (c.actor == 'SYSTEM' and pending
                      and now >= min(r['created'] + DAY, r['delivery']))
                if ok:
                    r.update(status='EXPIRED', closure=('expiry', '', now))
                    p['status'] = 'PUBLISHED'
            elif c.action == 'complete':
                ok = c.actor == r['buyer'] and confirmed
                if ok:
                    r.update(status='COMPLETED', completed=now)
                    p['status'] = 'SOLD'
        if ok:
            p['version'] += 1
            self.outcome = 'SUCCESS'
        elif c.action == 'expire':
            self.noop = True

    def commit(self, fail=None):
        if self.noop:
            self.rollback()
            return Reply('NO_CHANGE')
        # All writes are private until this model's atomic commit step.
        # Failure points express required behavior; they do not test SQL atomicity.
        if fail in FAILPOINTS:
            self.rollback()
            return Reply('TECHNICAL_ERROR')
        m, c = self.model, self.command
        if self.outcome == 'REJECTED':
            assert (self.product, self.records) == self.before
        m.products[c.product] = deepcopy(self.product)
        for rid, r in self.records.items():
            m.reservations[rid] = deepcopy(r)
        m.results[c.K] = dict(digest=c.digest, outcome=self.outcome,
                             reservation=self.rid if self.rid in m.reservations else None)
        m.audit.append((c.K, 'CHANGE' if self.outcome == 'SUCCESS' else 'FAILURE'))
        self.rollback()
        m.invariant()
        return Reply('COMMITTED', self.outcome, m.results[c.K]['reservation'])

    def rollback(self):
        self.model.key_locks.discard(self.command.K)
        if self.locked:
            self.model.product_locks.discard(self.command.product)
            self.locked = False


def booking(confirmed=False):
    m = Model()
    create = Command('A', 'create', 'create-A')
    rid = m.run(create).reservation
    if confirmed:
        m.run(Command('S', 'accept', 'accept-A', 1, reservation=rid), now=200)
    return m, create, rid


class DesignTests(unittest.TestCase):
    def test_all_six_booking_withdrawal_orders(self):
        commands = [Command('A', 'create', 'A'), Command('B', 'create', 'B'),
                    Command('S', 'takeDown', 'S')]
        for order in permutations(commands):
            with self.subTest(order=[c.actor for c in order]):
                m = Model()
                replies = [m.run(c) for c in order]
                self.assertEqual([r.outcome for r in replies], ['SUCCESS', 'REJECTED', 'REJECTED'])
                self.assertEqual(len(m.reservations), 0 if order[0].actor == 'S' else 1)
                m.invariant()

    def test_waiting_product_reads_committed_state(self):
        m = Model()
        a = m.begin(Command('A', 'create', 'A'))
        b = m.begin(Command('B', 'create', 'B'))
        self.assertTrue(a.lock_product())
        self.assertFalse(b.lock_product())
        a.apply(100)
        self.assertEqual(a.commit().outcome, 'SUCCESS')
        self.assertTrue(b.lock_product())
        self.assertEqual(b.product['status'], 'RESERVED')
        b.apply(100)
        self.assertEqual(b.commit().outcome, 'REJECTED')

    def test_rolled_back_lock_owner_does_not_win(self):
        for first in ('create', 'takeDown'):
            with self.subTest(first=first):
                m = Model()
                actor = 'A' if first == 'create' else 'S'
                tx = m.begin(Command(actor, first, 'first'))
                tx.lock_product(); tx.apply(100)
                self.assertEqual(tx.commit(fail='before_commit').code, 'TECHNICAL_ERROR')
                self.assertEqual(m.run(Command('B', 'create', 'next')).outcome, 'SUCCESS')

    def test_same_key_waits_and_replays_once(self):
        m = Model(); c = Command('A', 'create', 'same')
        tx = m.begin(c); tx.lock_product(); tx.apply(100)
        self.assertEqual(m.begin(c).code, 'WAIT_KEY')
        self.assertFalse(m.results)
        tx.commit()
        self.assertEqual(m.run(c).code, 'REPLAY')
        self.assertEqual((len(m.reservations), len(m.audit)), (1, 1))

    def test_same_key_after_rollback_executes(self):
        m = Model(); c = Command('A', 'create', 'same')
        tx = m.begin(c); tx.lock_product(); tx.apply(100); tx.rollback()
        self.assertEqual(m.run(c).outcome, 'SUCCESS')
        self.assertFalse(m.key_locks)

    def test_same_key_different_content_conflicts(self):
        m, c, rid = booking()
        for changed in (replace(c, product='Q'), replace(c, delivery=2000),
                        replace(c, place='square'), replace(c, version=1)):
            with self.subTest(changed=changed):
                self.assertEqual(m.run(changed).code, 'KEY_CONFLICT')
        self.assertEqual(len(m.reservations), 1)

    def test_same_key_different_target_waits_before_any_business(self):
        m = Model(); c = Command('A', 'create', 'same')
        tx = m.begin(c)
        self.assertEqual(m.begin(replace(c, product='Q')).code, 'WAIT_KEY')
        tx.rollback()

    def test_success_response_lost_after_later_cancellation(self):
        m, c, rid = booking()
        m.run(Command('A', 'cancel', 'cancel', 1, reservation=rid))
        old = m.run(c)
        self.assertEqual((old.code, old.outcome, old.reservation, old.current),
                         ('REPLAY', 'SUCCESS', rid, 'CANCELLED'))
        self.assertEqual(len(m.reservations), 1)

    def test_current_read_permission_still_required(self):
        m, c, _ = booking()
        self.assertEqual(m.run(c, readable=False).code, 'FORBIDDEN')

    def test_rejected_result_does_not_execute_later(self):
        m, _, rid = booking()
        rejected = Command('S', 'takeDown', 'down', 1)
        self.assertEqual(m.run(rejected).outcome, 'REJECTED')
        m.run(Command('A', 'cancel', 'cancel', 1, reservation=rid))
        self.assertEqual(m.run(rejected).outcome, 'REJECTED')
        self.assertEqual(m.products['P']['status'], 'PUBLISHED')
        self.assertEqual(m.run(replace(rejected, key='new-down', version=2)).outcome, 'SUCCESS')

    def test_failure_points_leave_no_partial_create_cancel_complete_ban(self):
        for action in ('create', 'cancel', 'complete', 'ban'):
            for point in FAILPOINTS:
                with self.subTest(action=action, point=point):
                    if action == 'create':
                        m = Model(); c = Command('A', action, 'fault')
                    else:
                        m, _, rid = booking(confirmed=action == 'complete')
                        actor = 'ADMIN' if action == 'ban' else 'A'
                        c = Command(actor, action, 'fault', m.products['P']['version'],
                                    reservation=rid, reason='reason')
                    before = deepcopy((m.products, m.reservations, m.results, m.audit))
                    self.assertEqual(m.run(c, fail=point).code, 'TECHNICAL_ERROR')
                    self.assertEqual((m.products, m.reservations, m.results, m.audit), before)
                    self.assertFalse(m.key_locks | m.product_locks)
                    self.assertEqual(m.run(c).outcome, 'SUCCESS')

    def test_deadline_before_equal_after(self):
        for now, outcome, state in [(999, 'SUCCESS', 'CONFIRMED'),
                                    (1000, 'REJECTED', 'EXPIRED'), (1001, 'REJECTED', 'EXPIRED')]:
            with self.subTest(now=now):
                m, _, rid = booking()
                r = m.run(Command('S', 'accept', 'accept', 1, reservation=rid), now=now)
                self.assertEqual((r.outcome, m.reservations[rid]['status']), (outcome, state))

    def test_expiry_survives_stale_invalid_create(self):
        m, _, rid = booking()
        failed = m.run(Command('B', 'create', 'new', 1, place='x'), now=1000)
        self.assertEqual(failed.outcome, 'REJECTED')
        self.assertEqual((m.products['P']['status'], m.reservations[rid]['status']),
                         ('PUBLISHED', 'EXPIRED'))
        self.assertEqual(m.products['P']['version'], 2)

    def test_confirmed_replay_after_deadline_does_not_expire(self):
        m, _, rid = booking()
        c = Command('S', 'accept', 'accept', 1, reservation=rid)
        m.run(c, now=999)
        self.assertEqual(m.run(c, now=2000).code, 'REPLAY')
        self.assertEqual(m.reservations[rid]['status'], 'CONFIRMED')
        self.assertEqual(m.run(Command('SYSTEM', 'expire', rid, None, reservation=rid), now=2000).code,
                         'NO_CHANGE')

    def test_old_cancel_and_expiry_leave_successor_unchanged(self):
        m, _, old = booking()
        cancel = Command('A', 'cancel', 'cancel', 1, reservation=old)
        m.run(cancel)
        new = m.run(Command('B', 'create', 'new', 2)).reservation
        before = deepcopy((m.products, m.reservations))
        self.assertEqual(m.run(cancel).code, 'REPLAY')
        m.run(Command('SYSTEM', 'expire', old, None, reservation=old), now=2000)
        m.run(replace(cancel, key='fresh-old-cancel', version=3))
        self.assertEqual((m.products, m.reservations), before)
        self.assertEqual(m.reservations[new]['status'], 'PENDING')

    def test_ban_complete_and_cancel_complete_competitions(self):
        for rival in ('ban', 'cancel'):
            for first in ('complete', rival):
                with self.subTest(rival=rival, first=first):
                    m, _, rid = booking(confirmed=True)
                    cmds = {'complete': Command('A', 'complete', 'complete', 2, reservation=rid),
                            rival: Command('ADMIN' if rival == 'ban' else 'S', rival, rival,
                                           2, reservation=rid, reason='reason')}
                    second = rival if first == 'complete' else 'complete'
                    self.assertEqual(m.run(cmds[first]).outcome, 'SUCCESS')
                    self.assertEqual(m.run(cmds[second]).outcome, 'REJECTED')
                    m.invariant()

    def test_seller_cancel_requires_confirmed_and_reason(self):
        for confirmed, reason, expected in [(False, 'reason', 'REJECTED'),
                                            (True, '', 'REJECTED'), (True, 'reason', 'SUCCESS')]:
            with self.subTest(confirmed=confirmed, reason=reason):
                m, _, rid = booking(confirmed=confirmed)
                c = Command('S', 'cancel', 'cancel', m.products['P']['version'],
                            reservation=rid, reason=reason)
                self.assertEqual(m.run(c).outcome, expected)

    def test_only_buyer_can_complete_confirmed(self):
        for confirmed, actor, expected in [(False, 'A', 'REJECTED'), (True, 'S', 'REJECTED'),
                                           (True, 'ADMIN', 'REJECTED'), (True, 'A', 'SUCCESS')]:
            with self.subTest(confirmed=confirmed, actor=actor):
                m, _, rid = booking(confirmed)
                self.assertEqual(m.run(Command(actor, 'complete', 'finish',
                    m.products['P']['version'], reservation=rid)).outcome, expected)

    def test_completion_replay_keeps_first_time_and_one_success(self):
        m, _, rid = booking(True)
        c = Command('A', 'complete', 'finish', 2, reservation=rid)
        m.run(c, now=300); m.run(c, now=900)
        self.assertEqual(m.reservations[rid]['completed'], 300)
        self.assertEqual(sum(a[0] == c.K and a[1] == 'CHANGE' for a in m.audit), 1)

    def test_normal_release_vs_platform_cancel(self):
        for action, actor, expected in [('reject', 'S', 'PUBLISHED'),
                                        ('cancel', 'A', 'PUBLISHED'), ('ban', 'ADMIN', 'BANNED')]:
            with self.subTest(action=action):
                m, _, rid = booking()
                m.run(Command(actor, action, action, 1, reservation=rid, reason='reason'))
                self.assertEqual(m.products['P']['status'], expected)
                self.assertEqual(m.products['P']['published'], 10)

    def test_nonbuyer_cannot_self_book(self):
        m = Model()
        self.assertEqual(m.run(Command('S', 'create', 'self')).outcome, 'REJECTED')
        self.assertFalse(m.reservations)

    def test_checker_detects_original_counterexamples(self):
        m, _, rid = booking()
        m.products['P']['status'] = 'OFF_SHELF'
        with self.assertRaises(AssertionError):
            m.invariant()
        m.products['P']['status'] = 'RESERVED'
        m.reservations['duplicate'] = deepcopy(m.reservations[rid])
        with self.assertRaises(AssertionError):
            m.invariant()

    def test_diagrams_share_business_interfaces_and_states(self):
        core = (ROOT / 'UML/UML类图.puml').read_text(encoding='utf-8')
        states = '\n'.join(p.read_text(encoding='utf-8') for p in (ROOT / 'UML').glob('*状态图*.puml'))
        methods = set(re.findall(r'^\s*\+(\w+)\(', core, re.M))
        expected = {'edit', 'submitForReview', 'withdrawReview', 'approveReview', 'rejectReview',
                    'takeDown', 'createReservation', 'acceptReservation', 'rejectReservation',
                    'cancelReservation', 'expireReservation', 'completeReservation', 'ban', 'markViolation'}
        self.assertEqual(methods, expected)
        for method in methods:
            self.assertIn(method + '(', states)
        for p in (ROOT / 'UML').glob('*.puml'):
            self.assertIsNone(re.search(r'Id\b', p.read_text(encoding='utf-8')), p.name)
        self.assertNotIn('activeReservationID', core)
        self.assertNotIn('currentReviewID', core)


if __name__ == '__main__':
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(DesignTests))
    output = stream.getvalue()
    print(output)
    (ROOT / 'validation/model-test-output.txt').write_text(output, encoding='utf-8')
    passed = result.wasSuccessful()
    report = f'''# 设计模型验证结果

运行命令：`python validation/check_design.py`。验证日期：2026-11-11。

- 测试方法数：{result.testsRun}；失败：{len(result.failures)}；错误：{len(result.errors)}。
- 模型结果：{'全部通过' if passed else '未通过，见原始记录'}。
- 三方竞争：枚举两名买家和卖家下架的全部 6 种顺序。
- 原子失败模型：创建、取消、完成、封禁 × 5 个提交前失败点，共 20 组。
- 其他覆盖：K 锁等待/回滚/重试、不同目标和内容冲突、丢响应后返回原对象当前状态、
  权限重查、拒绝结果重放、截止前/等于/之后、独立过期、后继预约保护、
  完成与取消/封禁竞争、角色限制、首次完成时间、普通释放/平台取消、接口覆盖。
- 反例检查：主动制造“下架仍有有效预约”和“两条有效预约”，确认不变量能检测到。

这里是离散设计模型，不是后端实现。提交原子性和锁的语义是模型前提；
没有运行真实 PostgreSQL、多线程 HTTP、连接池、进程崩溃或性能测试。
因此这些结果不能证明 SQL 实现正确、故障一定恢复或过期达到 60 秒指标。
真实集成验收清单见 `../UML图解析.md` 第 7 节。

原始输出：[model-test-output.txt](model-test-output.txt)。
'''
    (ROOT / 'validation/验证结果.md').write_text(report, encoding='utf-8')
    raise SystemExit(0 if passed else 1)
