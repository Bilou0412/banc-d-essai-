"""Red tests -- code layer, first attack.

The public interface of `app` is fixed by these tests:

    system = app.BookingSystem(now=<aware datetime>)
    system.advance(<timedelta>)                     # simulated time moves forward

    res = system.add_resource(name, capacity, timezone, opening, closing,
                              min_duration, max_duration, min_notice,
                              max_horizon, cancellation_deadline, waitlist)
        # timezone: IANA name (zoneinfo); opening/closing: datetime.time in the
        # resource's local wall time; the others are timedeltas; waitlist: bool
    system.set_capacity(res, n)                     # administrator action

    user = system.add_user(name, timezone, quota)

    b = system.request(user, res, start, end)       # start/end: NAIVE datetimes,
                                                    # wall time in the USER's zone
    system.status(b)          -> "confirmée" | "en attente" | "refusée" | "annulée"
    system.refusal_reason(b)  -> "quota atteint" | "hors horaires" | ... (None if not refused)
    system.waitlist_position(b) -> int (1 = first), None if not waiting
    system.cancel(b)          -> resulting status (never raises for a late attempt)
    system.active_bookings(user) -> int
    system.remaining(res, start, end) -> int        # NAIVE, wall time in the RESOURCE's zone
    system.displayed_start(b, viewer_user) -> aware datetime in the viewer's zone

    series = system.request_recurring(user, res, start, end, count)   # weekly, user wall time
    system.series_bookings(series)    -> list of booking ids, one per requested
                                         occurrence, chronological (refused included)
    system.created_occurrences(series) -> list of booking ids of the occurrences
                                         that were created (i.e. not refused)
"""

import sys
import threading
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

import app

PARIS = "Europe/Paris"
NY = "America/New_York"
UTC = "UTC"

CONFIRMED = "confirmée"
WAITING = "en attente"
REFUSED = "refusée"
CANCELLED = "annulée"

# Monday 5 January 2026, 08:00 Paris
NOW = datetime(2026, 1, 5, 8, 0, tzinfo=ZoneInfo(PARIS))

# Wednesday 7 January 2026, 10:00-11:00 (wall time)
S = datetime(2026, 1, 7, 10, 0)
E = datetime(2026, 1, 7, 11, 0)


# ---------------------------------------------------------------- helpers

def make_system(now=NOW):
    return app.BookingSystem(now=now)


def make_resource(system, **kw):
    params = dict(
        name="Salle A",
        capacity=10,
        timezone=PARIS,
        opening=time(9, 0),
        closing=time(18, 0),
        min_duration=timedelta(minutes=30),
        max_duration=timedelta(hours=2),
        min_notice=timedelta(hours=1),
        max_horizon=timedelta(days=120),
        cancellation_deadline=timedelta(hours=24),
        waitlist=True,
    )
    params.update(kw)
    return system.add_resource(**params)


_counter = [0]


def make_user(system, name=None, timezone=PARIS, quota=10**6):
    if name is None:
        _counter[0] += 1
        name = f"u{_counter[0]}"
    return system.add_user(name=name, timezone=timezone, quota=quota)


def fill(system, res, start, end, n):
    ids = []
    for _ in range(n):
        u = make_user(system)
        b = system.request(u, res, start, end)
        assert system.status(b) == CONFIRMED, (
            f"setup: filler booking expected {CONFIRMED!r}, got {system.status(b)!r}"
        )
        ids.append(b)
    return ids


def hm(dt):
    return (dt.hour, dt.minute)


@pytest.fixture
def fast_switch():
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(old)


def run_concurrently(fns):
    barrier = threading.Barrier(len(fns))
    results = [None] * len(fns)
    errors = []

    def worker(i, fn):
        try:
            barrier.wait()
            results[i] = fn()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i, f)) for i, f in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors, f"exceptions raised in concurrent requests: {errors!r}"
    return results


# ---------------------------------------------------------------- A01

def test_A01_empty_resource_capacity_10_shows_10():
    s = make_system()
    r = make_resource(s, capacity=10)
    got = s.remaining(r, S, E)
    assert got == 10, f"expected 10 remaining places on an empty slot, got {got!r}"


def test_A01_empty_resource_capacity_1_shows_1():
    s = make_system()
    r = make_resource(s, capacity=1)
    got = s.remaining(r, S, E)
    assert got == 1, f"expected 1 remaining place (capacity 1), got {got!r}"


# ---------------------------------------------------------------- A02 / A03

def test_A02_request_with_3_remaining_is_confirmed():
    s = make_system()
    r = make_resource(s, capacity=10)
    fill(s, r, S, E, 7)
    assert s.remaining(r, S, E) == 3
    u = make_user(s)
    b = s.request(u, r, S, E)
    assert s.status(b) == CONFIRMED, f"expected {CONFIRMED!r}, got {s.status(b)!r}"


def test_A03_confirmed_booking_on_3_remaining_leaves_2():
    s = make_system()
    r = make_resource(s, capacity=10)
    fill(s, r, S, E, 7)
    u = make_user(s)
    s.request(u, r, S, E)
    got = s.remaining(r, S, E)
    assert got == 2, f"expected 2 remaining places, got {got!r}"


def test_A03_booking_on_other_slot_does_not_consume_this_slot():
    s = make_system()
    r = make_resource(s, capacity=3)
    u = make_user(s)
    s.request(u, r, datetime(2026, 1, 8, 10, 0), datetime(2026, 1, 8, 11, 0))
    got = s.remaining(r, S, E)
    assert got == 3, f"expected 3 (booking was on another day), got {got!r}"


# ---------------------------------------------------------------- A04 / A05

def test_A04_full_slot_with_waitlist_puts_request_waiting():
    s = make_system()
    r = make_resource(s, capacity=2, waitlist=True)
    fill(s, r, S, E, 2)
    b = s.request(make_user(s), r, S, E)
    assert s.status(b) == WAITING, f"expected {WAITING!r}, got {s.status(b)!r}"
    assert s.remaining(r, S, E) == 0, "a waiting request must not change remaining places"


def test_A05_full_slot_without_waitlist_refuses_request():
    s = make_system()
    r = make_resource(s, capacity=2, waitlist=False)
    fill(s, r, S, E, 2)
    b = s.request(make_user(s), r, S, E)
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


# ---------------------------------------------------------------- A06

def test_A06_third_waiter_gets_position_3():
    s = make_system()
    r = make_resource(s, capacity=1, waitlist=True)
    fill(s, r, S, E, 1)
    w1 = s.request(make_user(s), r, S, E)
    w2 = s.request(make_user(s), r, S, E)
    w3 = s.request(make_user(s), r, S, E)
    assert s.waitlist_position(w1) == 1
    assert s.waitlist_position(w2) == 2
    got = s.waitlist_position(w3)
    assert got == 3, f"expected waitlist position 3, got {got!r}"


def test_A06_concurrent_waiters_get_distinct_positions(fast_switch):
    for trial in range(40):
        s = make_system()
        r = make_resource(s, capacity=1, waitlist=True)
        fill(s, r, S, E, 1)
        users = [make_user(s) for _ in range(10)]
        ids = run_concurrently([(lambda u=u: s.request(u, r, S, E)) for u in users])
        statuses = [s.status(b) for b in ids]
        assert statuses == [WAITING] * 10, f"trial {trial}: expected all waiting, got {statuses!r}"
        positions = sorted(s.waitlist_position(b) for b in ids)
        assert positions == list(range(1, 11)), (
            f"trial {trial}: concurrent waiters must get positions 1..10, got {positions!r}"
        )


# ---------------------------------------------------------------- A07 / A08

def test_A07_waiting_request_does_not_increase_active_bookings():
    s = make_system()
    r = make_resource(s, capacity=1, waitlist=True)
    fill(s, r, S, E, 1)
    u = make_user(s)
    s.request(u, r, datetime(2026, 1, 8, 10, 0), datetime(2026, 1, 8, 11, 0))
    before = s.active_bookings(u)
    assert before == 1
    b = s.request(u, r, S, E)
    assert s.status(b) == WAITING
    after = s.active_bookings(u)
    assert after == before, f"expected active bookings to stay {before}, got {after}"


def test_A08_confirmed_booking_increases_active_bookings_by_1():
    s = make_system()
    r = make_resource(s)
    u = make_user(s)
    assert s.active_bookings(u) == 0
    b = s.request(u, r, S, E)
    assert s.status(b) == CONFIRMED
    got = s.active_bookings(u)
    assert got == 1, f"expected 1 active booking, got {got}"


def test_A08_refused_request_does_not_increase_active_bookings():
    s = make_system()
    r = make_resource(s, capacity=1, waitlist=False)
    fill(s, r, S, E, 1)
    u = make_user(s)
    b = s.request(u, r, S, E)
    assert s.status(b) == REFUSED
    assert s.active_bookings(u) == 0, f"refused request counted: {s.active_bookings(u)}"


# ---------------------------------------------------------------- A09 / A10 / A11

def _user_at_quota(s, r, quota):
    u = make_user(s, quota=quota)
    for d in range(quota):
        b = s.request(u, r, datetime(2026, 1, 8 + d, 10, 0), datetime(2026, 1, 8 + d, 11, 0))
        assert s.status(b) == CONFIRMED
    assert s.active_bookings(u) == quota
    return u


def test_A09_user_at_quota_is_refused():
    s = make_system()
    r = make_resource(s)
    u = _user_at_quota(s, r, 2)
    b = s.request(u, r, S, E)
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


def test_A09_user_at_quota_is_refused_even_if_waitlist_would_apply():
    s = make_system()
    r = make_resource(s, capacity=1, waitlist=True)
    fill(s, r, S, E, 1)
    u = _user_at_quota(s, r, 2)
    b = s.request(u, r, S, E)
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


def test_A09_concurrent_requests_cannot_exceed_quota(fast_switch):
    slots = [(datetime(2026, 1, 7 + d, h, 0), datetime(2026, 1, 7 + d, h + 1, 0))
             for d in range(2) for h in range(9, 15)]
    for trial in range(40):
        s = make_system()
        r = make_resource(s)
        u = make_user(s, quota=3)
        ids = run_concurrently([(lambda a=a, b=b: s.request(u, r, a, b)) for a, b in slots])
        confirmed = [b for b in ids if s.status(b) == CONFIRMED]
        assert len(confirmed) == 3, (
            f"trial {trial}: quota 3 under concurrency, expected 3 confirmed, got {len(confirmed)}"
        )
        assert s.active_bookings(u) == 3


def test_A10_user_at_quota_reason_is_quota_atteint():
    s = make_system()
    r = make_resource(s)
    u = _user_at_quota(s, r, 2)
    b = s.request(u, r, S, E)
    got = s.refusal_reason(b)
    assert got == "quota atteint", f"expected 'quota atteint', got {got!r}"


def test_A11_user_one_below_quota_is_confirmed():
    s = make_system()
    r = make_resource(s)
    u = make_user(s, quota=3)
    for d in range(2):
        s.request(u, r, datetime(2026, 1, 8 + d, 10, 0), datetime(2026, 1, 8 + d, 11, 0))
    assert s.active_bookings(u) == 2
    b = s.request(u, r, S, E)
    assert s.status(b) == CONFIRMED, f"expected {CONFIRMED!r}, got {s.status(b)!r}"


# ---------------------------------------------------------------- A12 / A13 / A14

def test_A12_start_before_opening_is_refused():
    s = make_system()
    r = make_resource(s)
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 8, 30), datetime(2026, 1, 7, 9, 30))
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


def test_A12_opening_is_resource_wall_time_in_summer():
    # 07:00 UTC on 8 July = 09:00 in Paris (CEST, UTC+2). A fixed UTC+1 offset sees 08:00.
    s = make_system()
    r = make_resource(s, max_horizon=timedelta(days=365))
    u = make_user(s, timezone=UTC)
    b = s.request(u, r, datetime(2026, 7, 8, 7, 0), datetime(2026, 7, 8, 8, 0))
    assert s.status(b) == CONFIRMED, (
        f"09:00 Paris summer time is within opening hours: expected {CONFIRMED!r}, got {s.status(b)!r}"
    )
    b2 = s.request(u, r, datetime(2026, 7, 8, 6, 30), datetime(2026, 7, 8, 7, 30))
    assert s.status(b2) == REFUSED, (
        f"08:30 Paris summer time is before opening: expected {REFUSED!r}, got {s.status(b2)!r}"
    )


def test_A13_end_after_closing_is_refused():
    s = make_system()
    r = make_resource(s)
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 17, 30), datetime(2026, 1, 7, 18, 30))
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


def test_A13_end_exactly_at_closing_is_accepted():
    s = make_system()
    r = make_resource(s)
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 17, 0), datetime(2026, 1, 7, 18, 0))
    assert s.status(b) == CONFIRMED, f"ending at closing is not after it: got {s.status(b)!r}"


def test_A13_closing_is_resource_wall_time_in_summer():
    # 16:30-17:00 UTC on 8 July = 18:30-19:00 Paris (CEST). A fixed UTC+1 offset sees 17:30-18:00.
    s = make_system()
    r = make_resource(s, max_horizon=timedelta(days=365))
    u = make_user(s, timezone=UTC)
    b = s.request(u, r, datetime(2026, 7, 8, 16, 30), datetime(2026, 7, 8, 17, 0))
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


def test_A14_outside_hours_reason_is_hors_horaires():
    s = make_system()
    r = make_resource(s)
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 8, 0), datetime(2026, 1, 7, 9, 0))
    got = s.refusal_reason(b)
    assert got == "hors horaires", f"expected 'hors horaires', got {got!r}"
    b2 = s.request(make_user(s), r, datetime(2026, 1, 7, 17, 30), datetime(2026, 1, 7, 18, 30))
    got2 = s.refusal_reason(b2)
    assert got2 == "hors horaires", f"expected 'hors horaires' (after closing), got {got2!r}"


# ---------------------------------------------------------------- A15 / A16 / A17

def test_A15_shorter_than_min_duration_is_refused():
    s = make_system()
    r = make_resource(s, min_duration=timedelta(minutes=30))
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 10, 0), datetime(2026, 1, 7, 10, 15))
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


def test_A15_trou_duree_egale_minimum_confirmee():
    s = make_system()
    r = make_resource(s, min_duration=timedelta(minutes=30))
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 10, 0), datetime(2026, 1, 7, 10, 30))
    assert s.status(b) == CONFIRMED, f"duration == minimum: expected {CONFIRMED!r}, got {s.status(b)!r}"


def test_A16_longer_than_max_duration_is_refused():
    s = make_system()
    r = make_resource(s, max_duration=timedelta(hours=2))
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 10, 0), datetime(2026, 1, 7, 12, 30))
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


def test_A17_exactly_max_duration_is_confirmed():
    s = make_system()
    r = make_resource(s, max_duration=timedelta(hours=2))
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 10, 0), datetime(2026, 1, 7, 12, 0))
    assert s.status(b) == CONFIRMED, f"expected {CONFIRMED!r}, got {s.status(b)!r}"


def test_A17_duration_measured_in_real_time_across_dst():
    # A resource open all night: 29 March 2026, 01:30-04:00 Paris wall time is only
    # 1h30 of real time (02:00 -> 03:00 jump). Max 2h: must be confirmed.
    s = make_system()
    r = make_resource(s, opening=time(0, 0), closing=time(23, 59),
                      max_duration=timedelta(hours=2))
    b = s.request(make_user(s), r, datetime(2026, 3, 29, 1, 30), datetime(2026, 3, 29, 4, 0))
    assert s.status(b) == CONFIRMED, (
        f"1h30 of real time across the DST jump: expected {CONFIRMED!r}, got {s.status(b)!r}"
    )


# ---------------------------------------------------------------- A18 / A19

def test_A18_start_within_min_notice_is_refused():
    s = make_system()
    r = make_resource(s, min_notice=timedelta(hours=1))
    s.advance(timedelta(minutes=30))  # now 08:30 Paris
    b = s.request(make_user(s), r, datetime(2026, 1, 5, 9, 0), datetime(2026, 1, 5, 10, 0))
    assert s.status(b) == REFUSED, f"30 min notice < 1h: expected {REFUSED!r}, got {s.status(b)!r}"


def test_A18_trou_preavis_exactement_egal_confirme():
    s = make_system()  # now 08:00 Paris
    r = make_resource(s, min_notice=timedelta(hours=1))
    b = s.request(make_user(s), r, datetime(2026, 1, 5, 9, 0), datetime(2026, 1, 5, 10, 0))
    assert s.status(b) == CONFIRMED, f"notice == 1h: expected {CONFIRMED!r}, got {s.status(b)!r}"


def test_A18_notice_uses_advanced_clock():
    s = make_system()
    r = make_resource(s, min_notice=timedelta(hours=1))
    s.advance(timedelta(days=2, hours=1, minutes=30))  # now 7 Jan 09:30
    b = s.request(make_user(s), r, datetime(2026, 1, 7, 10, 0), datetime(2026, 1, 7, 11, 0))
    assert s.status(b) == REFUSED, f"clock advanced, 30 min notice: got {s.status(b)!r}"


def test_A19_beyond_max_horizon_is_refused():
    s = make_system()
    r = make_resource(s, max_horizon=timedelta(days=120))  # horizon: 5 May 2026 08:00
    b = s.request(make_user(s), r, datetime(2026, 5, 20, 10, 0), datetime(2026, 5, 20, 11, 0))
    assert s.status(b) == REFUSED, f"expected {REFUSED!r}, got {s.status(b)!r}"


def test_A19_within_horizon_is_confirmed():
    s = make_system()
    r = make_resource(s, max_horizon=timedelta(days=120))
    b = s.request(make_user(s), r, datetime(2026, 5, 4, 10, 0), datetime(2026, 5, 4, 11, 0))
    assert s.status(b) == CONFIRMED, f"expected {CONFIRMED!r}, got {s.status(b)!r}"


# ---------------------------------------------------------------- A20 / A21 / A22 / A23

def test_A20_cancel_before_deadline_sets_cancelled():
    s = make_system()
    r = make_resource(s, cancellation_deadline=timedelta(hours=24))
    b = s.request(make_user(s), r, S, E)
    s.cancel(b)
    assert s.status(b) == CANCELLED, f"expected {CANCELLED!r}, got {s.status(b)!r}"


def test_A21_cancel_after_deadline_stays_confirmed():
    s = make_system()
    r = make_resource(s, cancellation_deadline=timedelta(hours=24))
    b = s.request(make_user(s), r, S, E)
    s.advance(timedelta(hours=27))  # 6 Jan 11:00, 23h before start
    s.cancel(b)
    assert s.status(b) == CONFIRMED, f"expected {CONFIRMED!r}, got {s.status(b)!r}"


def test_A21_late_cancel_does_not_free_place():
    s = make_system()
    r = make_resource(s, capacity=2, cancellation_deadline=timedelta(hours=24))
    u = make_user(s)
    b = s.request(u, r, S, E)
    s.advance(timedelta(hours=27))
    s.cancel(b)
    assert s.remaining(r, S, E) == 1, f"late cancel freed a place: {s.remaining(r, S, E)}"
    assert s.active_bookings(u) == 1


def test_A21_trou_annulation_a_l_echeance_exacte_refusee():
    s = make_system()
    r = make_resource(s, cancellation_deadline=timedelta(hours=24))
    b = s.request(make_user(s), r, S, E)
    s.advance(timedelta(hours=26))  # 6 Jan 10:00, exactly 24h before
    s.cancel(b)
    assert s.status(b) == CONFIRMED, f"at the deadline: expected {CONFIRMED!r}, got {s.status(b)!r}"


def test_A22_cancel_decreases_active_bookings_by_1():
    s = make_system()
    r = make_resource(s)
    u = make_user(s)
    b = s.request(u, r, S, E)
    s.request(u, r, datetime(2026, 1, 8, 10, 0), datetime(2026, 1, 8, 11, 0))
    assert s.active_bookings(u) == 2
    s.cancel(b)
    got = s.active_bookings(u)
    assert got == 1, f"expected 1 active booking, got {got}"


def test_A22_double_cancel_decreases_only_once():
    s = make_system()
    r = make_resource(s)
    u = make_user(s)
    b = s.request(u, r, S, E)
    s.request(u, r, datetime(2026, 1, 8, 10, 0), datetime(2026, 1, 8, 11, 0))
    s.cancel(b)
    s.cancel(b)
    got = s.active_bookings(u)
    assert got == 1, f"cancelling twice must not decrease twice: got {got}"


def test_A23_cancel_with_empty_waitlist_frees_one_place():
    s = make_system()
    r = make_resource(s, capacity=3)
    b = s.request(make_user(s), r, S, E)
    fill(s, r, S, E, 1)
    assert s.remaining(r, S, E) == 1
    s.cancel(b)
    got = s.remaining(r, S, E)
    assert got == 2, f"expected 2 remaining places, got {got}"


def test_A23_double_cancel_frees_only_one_place():
    s = make_system()
    r = make_resource(s, capacity=3)
    b = s.request(make_user(s), r, S, E)
    s.cancel(b)
    s.cancel(b)
    got = s.remaining(r, S, E)
    assert got == 3, f"remaining must not exceed capacity: got {got}"


# ---------------------------------------------------------------- A24 / A25 / A26

def _full_with_two_waiters(s):
    r = make_resource(s, capacity=1, waitlist=True)
    holder = s.request(make_user(s), r, S, E)
    w1_user = make_user(s)
    w1 = s.request(w1_user, r, S, E)
    w2 = s.request(make_user(s), r, S, E)
    assert s.status(w1) == WAITING and s.status(w2) == WAITING
    return r, holder, w1, w2, w1_user


def test_A24_cancel_promotes_first_waiter():
    s = make_system()
    r, holder, w1, w2, _ = _full_with_two_waiters(s)
    s.cancel(holder)
    assert s.status(w1) == CONFIRMED, f"first waiter: expected {CONFIRMED!r}, got {s.status(w1)!r}"
    assert s.status(w2) == WAITING, f"second waiter: expected {WAITING!r}, got {s.status(w2)!r}"


def test_A24_trou_promu_compte_dans_reservations_actives():
    s = make_system()
    r, holder, w1, w2, w1_user = _full_with_two_waiters(s)
    assert s.active_bookings(w1_user) == 0
    s.cancel(holder)
    got = s.active_bookings(w1_user)
    assert got == 1, f"promoted user should have 1 active booking, got {got}"


def test_A25_cancel_with_waiters_keeps_remaining_at_0():
    s = make_system()
    r, holder, w1, w2, _ = _full_with_two_waiters(s)
    s.cancel(holder)
    got = s.remaining(r, S, E)
    assert got == 0, f"expected 0 remaining places, got {got}"


def test_A26_second_waiter_moves_to_position_1():
    s = make_system()
    r, holder, w1, w2, _ = _full_with_two_waiters(s)
    s.cancel(holder)
    got = s.waitlist_position(w2)
    assert got == 1, f"expected position 1, got {got!r}"


# ---------------------------------------------------------------- A27

def test_A27_capacity_reduced_5_to_3_with_2_confirmed_shows_1():
    s = make_system()
    r = make_resource(s, capacity=5)
    fill(s, r, S, E, 2)
    s.set_capacity(r, 3)
    got = s.remaining(r, S, E)
    assert got == 1, f"expected 1 remaining place, got {got}"


def test_A27_trou_capacite_sous_les_confirmees_affiche_0():
    s = make_system()
    r = make_resource(s, capacity=5)
    fill(s, r, S, E, 2)
    s.set_capacity(r, 1)
    got = s.remaining(r, S, E)
    assert got == 0, f"remaining places must never be negative, got {got}"


# ---------------------------------------------------------------- A28 (real concurrency)

def test_A28_two_simultaneous_requests_for_last_place(fast_switch):
    for trial in range(200):
        s = make_system()
        r = make_resource(s, capacity=3, waitlist=False)
        fill(s, r, S, E, 2)
        a, b = make_user(s), make_user(s)
        ids = run_concurrently([lambda: s.request(a, r, S, E), lambda: s.request(b, r, S, E)])
        statuses = sorted(s.status(x) for x in ids)
        assert statuses == sorted([CONFIRMED, REFUSED]), (
            f"trial {trial}: expected one confirmed and one refused, got {statuses!r}"
        )
        assert s.remaining(r, S, E) == 0


def test_A28_many_simultaneous_requests_never_overbook(fast_switch):
    s = make_system()
    r = make_resource(s, capacity=1, waitlist=False)
    users = [make_user(s) for _ in range(8)]
    slots = [(datetime(2026, 1, 7 + d, h, 0), datetime(2026, 1, 7 + d, h + 1, 0))
             for d in range(20) for h in range(9, 17)]
    for a, e in slots:
        ids = run_concurrently([(lambda u=u: s.request(u, r, a, e)) for u in users])
        statuses = [s.status(x) for x in ids]
        assert statuses.count(CONFIRMED) == 1 and statuses.count(REFUSED) == 7, (
            f"slot {a}: expected 1 confirmed / 7 refused, got {statuses!r}"
        )
        assert s.remaining(r, a, e) == 0


# ---------------------------------------------------------------- A29 / A30 / A31

def test_A29_paris_15h_shown_9h_in_new_york():
    s = make_system()
    r = make_resource(s)
    paris = make_user(s, timezone=PARIS)
    ny = make_user(s, timezone=NY)
    b = s.request(paris, r, datetime(2026, 1, 7, 15, 0), datetime(2026, 1, 7, 16, 0))
    d = s.displayed_start(b, ny)
    assert hm(d) == (9, 0), f"expected 09:00 in New York, got {d!r}"
    assert d.date() == datetime(2026, 1, 7).date()


def test_A29_trou_decalage_pendant_ecart_heure_ete():
    # 18 March 2026: New York already on EDT (since 8 March), Paris still on CET (until 29 March).
    s = make_system()
    r = make_resource(s)
    paris = make_user(s, timezone=PARIS)
    ny = make_user(s, timezone=NY)
    b = s.request(paris, r, datetime(2026, 3, 18, 15, 0), datetime(2026, 3, 18, 16, 0))
    d = s.displayed_start(b, ny)
    assert hm(d) == (10, 0), f"expected 10:00 in New York during the DST gap, got {d!r}"


def test_A30_same_zone_no_shift():
    s = make_system()
    r = make_resource(s)
    paris = make_user(s, timezone=PARIS)
    other = make_user(s, timezone=PARIS)
    b = s.request(paris, r, datetime(2026, 1, 7, 15, 0), datetime(2026, 1, 7, 16, 0))
    d = s.displayed_start(b, other)
    assert hm(d) == (15, 0), f"expected 15:00, got {d!r}"


def test_A30_same_zone_no_shift_in_summer():
    s = make_system()
    r = make_resource(s, max_horizon=timedelta(days=365))
    paris = make_user(s, timezone=PARIS)
    b = s.request(paris, r, datetime(2026, 7, 8, 15, 0), datetime(2026, 7, 8, 16, 0))
    d = s.displayed_start(b, paris)
    assert hm(d) == (15, 0), f"expected 15:00 in summer, got {d!r}"


def test_A31_new_york_8h_is_14h_paris_confirmed():
    s = make_system()
    r = make_resource(s)
    ny = make_user(s, timezone=NY)
    paris = make_user(s, timezone=PARIS)
    b = s.request(ny, r, datetime(2026, 1, 7, 8, 0), datetime(2026, 1, 7, 9, 0))
    assert s.status(b) == CONFIRMED, f"expected {CONFIRMED!r}, got {s.status(b)!r}"
    d = s.displayed_start(b, paris)
    assert hm(d) == (14, 0), f"expected 14:00 for a Paris viewer, got {d!r}"


def test_A31_new_york_request_during_dst_gap_uses_real_offset():
    # 18 March 2026, 12:00-13:00 EDT = 17:00-18:00 CET: inside hours.
    # A fixed 6h offset sees 18:00-19:00 and would refuse.
    s = make_system()
    r = make_resource(s)
    ny = make_user(s, timezone=NY)
    b = s.request(ny, r, datetime(2026, 3, 18, 12, 0), datetime(2026, 3, 18, 13, 0))
    assert s.status(b) == CONFIRMED, f"expected {CONFIRMED!r}, got {s.status(b)!r}"
    # 03:30-04:30 EDT = 08:30-09:30 CET: before opening. Fixed 6h sees 09:30.
    b2 = s.request(ny, r, datetime(2026, 3, 18, 3, 30), datetime(2026, 3, 18, 4, 30))
    assert s.status(b2) == REFUSED, f"expected {REFUSED!r}, got {s.status(b2)!r}"


# ---------------------------------------------------------------- A32 / A33

def test_A32_weekly_10h_paris_stays_10h_after_dst_change():
    s = make_system()
    r = make_resource(s)
    paris = make_user(s, timezone=PARIS)
    series = s.request_recurring(paris, r, datetime(2026, 3, 25, 10, 0),
                                 datetime(2026, 3, 25, 11, 0), 2)
    ids = s.series_bookings(series)
    assert len(ids) == 2
    before, after = (s.displayed_start(b, paris) for b in ids)
    assert hm(before) == (10, 0), f"25 March: expected 10:00, got {before!r}"
    assert hm(after) == (10, 0), f"1 April (after DST): expected 10:00, got {after!r}"
    assert after.date() == datetime(2026, 4, 1).date()


def test_A33_weekly_10h_paris_shifts_for_new_york_after_paris_dst():
    s = make_system()
    r = make_resource(s)
    paris = make_user(s, timezone=PARIS)
    ny = make_user(s, timezone=NY)
    series = s.request_recurring(paris, r, datetime(2026, 3, 4, 10, 0),
                                 datetime(2026, 3, 4, 11, 0), 5)
    ids = s.series_bookings(series)
    hours = [hm(s.displayed_start(b, ny)) for b in ids]
    # 4 Mar: CET/EST -> 04:00 ; 11,18,25 Mar: CET/EDT -> 05:00 ; 1 Apr: CEST/EDT -> 04:00
    assert hours == [(4, 0), (5, 0), (5, 0), (5, 0), (4, 0)], (
        f"expected NY display 04:00,05:00,05:00,05:00,04:00, got {hours!r}"
    )


# ---------------------------------------------------------------- A34 .. A39

def _weekly(s, u, r, count=4, start=S, end=E):
    return s.request_recurring(u, r, start, end, count)


def test_A34_weekly_4_all_available_creates_4():
    s = make_system()
    r = make_resource(s)
    u = make_user(s)
    series = _weekly(s, u, r)
    created = s.created_occurrences(series)
    assert len(created) == 4, f"expected 4 occurrences, got {len(created)}"
    assert all(s.status(b) == CONFIRMED for b in created)
    dates = [s.displayed_start(b, u).date() for b in created]
    assert dates == [datetime(2026, 1, d).date() for d in (7, 14, 21, 28)], f"got {dates!r}"


def _series_with_full_third_week(s):
    r = make_resource(s, capacity=1, waitlist=False)
    s.request(make_user(s), r, datetime(2026, 1, 21, 10, 0), datetime(2026, 1, 21, 11, 0))
    u = make_user(s)
    series = _weekly(s, u, r)
    return r, u, series


def test_A35_full_occurrence_without_waitlist_is_refused():
    s = make_system()
    r, u, series = _series_with_full_third_week(s)
    statuses = [s.status(b) for b in s.series_bookings(series)]
    assert statuses == [CONFIRMED, CONFIRMED, REFUSED, CONFIRMED], f"got {statuses!r}"


def test_A36_full_occurrence_without_waitlist_creates_3():
    s = make_system()
    r, u, series = _series_with_full_third_week(s)
    created = s.created_occurrences(series)
    assert len(created) == 3, f"expected 3 created occurrences, got {len(created)}"
    assert s.active_bookings(u) == 3


def test_A36_trou_occurrence_refusee_visible_non_comptee():
    s = make_system()
    r, u, series = _series_with_full_third_week(s)
    all_ids = s.series_bookings(series)
    created = s.created_occurrences(series)
    assert len(all_ids) == 4, f"the refused occurrence must remain visible: got {len(all_ids)} ids"
    refused = [b for b in all_ids if b not in created]
    assert len(refused) == 1 and s.status(refused[0]) == REFUSED


def test_A37_last_occurrence_beyond_horizon_not_created():
    s = make_system()
    r = make_resource(s, max_horizon=timedelta(days=120))  # horizon 5 May 08:00
    u = make_user(s)
    series = _weekly(s, u, r, 4, datetime(2026, 4, 14, 10, 0), datetime(2026, 4, 14, 11, 0))
    created = s.created_occurrences(series)
    dates = [s.displayed_start(b, u).date() for b in created]
    assert dates == [datetime(2026, 4, d).date() for d in (14, 21, 28)], (
        f"expected 14, 21, 28 April only (5 May is beyond horizon), got {dates!r}"
    )
    assert s.active_bookings(u) == 3


def test_A38_weekly_4_confirmed_adds_4_active():
    s = make_system()
    r = make_resource(s)
    u = make_user(s)
    s.request(u, r, datetime(2026, 1, 8, 10, 0), datetime(2026, 1, 8, 11, 0))
    before = s.active_bookings(u)
    _weekly(s, u, r)
    got = s.active_bookings(u) - before
    assert got == 4, f"expected +4 active bookings, got +{got}"


def test_A39_cancel_one_occurrence_keeps_next_confirmed():
    s = make_system()
    r = make_resource(s)
    u = make_user(s)
    series = _weekly(s, u, r)
    ids = s.series_bookings(series)
    s.cancel(ids[1])
    assert s.status(ids[1]) == CANCELLED, f"cancelled occurrence: got {s.status(ids[1])!r}"
    assert s.status(ids[2]) == CONFIRMED, f"next occurrence: expected {CONFIRMED!r}, got {s.status(ids[2])!r}"
    assert s.status(ids[0]) == CONFIRMED
    assert s.status(ids[3]) == CONFIRMED
    assert s.active_bookings(u) == 3


# ---------------------------------------------------------------- quota vs waitlist

def test_A07_trou_attente_ne_compte_pas_dans_quota():
    s = make_system()
    r = make_resource(s, capacity=1, waitlist=True)
    fill(s, r, S, E, 1)
    u = make_user(s, quota=1)
    w = s.request(u, r, S, E)
    assert s.status(w) == WAITING
    b = s.request(u, r, datetime(2026, 1, 8, 10, 0), datetime(2026, 1, 8, 11, 0))
    assert s.status(b) == CONFIRMED, (
        f"a waiting request is not active: quota 1 not reached, expected {CONFIRMED!r}, got {s.status(b)!r}"
    )
