"""The circuit breaker in the database: holds pause sends atomically, per
campaign or channel; only owners/admins resume (with a note), which re-queues
held sends; people's stop/revoke rights; and a pause racing a send."""
import os
import threading
import time
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")


@pytest.fixture
def live(db, new_user, act_as, as_admin):
    owner, approver, viewer, outsider = new_user(), new_user(), new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'approver'), (%s, %s, 'viewer')",
               (org, approver, org, viewer))
    cid = db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id, status) values ('Coffee', 'other', %s, %s, 'awaiting_metrics') returning id",
        (owner, org),
    ).fetchone()[0]
    return {"org": org, "owner": owner, "approver": approver, "viewer": viewer, "outsider": outsider, "campaign": cid}


def hold(db, c, trigger="EXPIRED_OFFER", severity="critical", channel=None):
    return db.execute("select place_hold(%s, %s, %s, 'The offer ended', '{}'::jsonb, %s)",
                      (c["campaign"], trigger, severity, channel)).fetchone()[0]


def claim(db, c, channel="bluesky"):
    return db.execute("select verdict, note from claim_delivery(%s, 1, %s, null, %s)",
                      (str(c["campaign"]), channel, Jsonb({"copy_text": "hi"}))).fetchone()


def as_user(db, act_as, as_admin, user, sql, params):
    act_as(user)
    db.execute("savepoint s")
    try:
        db.execute(sql, params)
        db.execute("release savepoint s")
        result = "ok"
    except psycopg.Error as exc:
        db.execute("rollback to savepoint s")
        result = str(exc).split("\n")[0]
    as_admin()
    return result


def test_a_critical_hold_pauses_every_send_and_is_kept_once(db, live):
    first = hold(db, live)
    assert hold(db, live) == first  # the same condition again: one active hold
    assert db.execute("select paused_at is not null from campaigns where id = %s", (live["campaign"],)).fetchone()[0]
    verdict, note = claim(db, live)
    assert verdict == "held" and note.startswith("held: EXPIRED_OFFER")
    assert db.execute("select status from deliveries where campaign_id = %s", (str(live["campaign"]),)).fetchone()[0] == "held"
    assert db.execute("select count(*) from audit_log where action = 'circuit.paused' and target_id = %s",
                      (str(live["campaign"]),)).fetchone()[0] == 1


def test_a_channel_hold_stops_only_that_channel(db, live):
    hold(db, live, "POLICY_VIOLATION", channel="email")
    assert claim(db, live, "email")[0] == "held"
    assert claim(db, live, "email_b")[0] == "held"  # variant B is email too
    assert claim(db, live, "bluesky")[0] == "go"


def test_a_warning_notifies_but_doesnt_pause(db, live):
    hold(db, live, "BRAND_RISK", severity="warning")
    assert claim(db, live)[0] == "go"
    assert not db.execute("select paused_at is not null from campaigns where id = %s", (live["campaign"],)).fetchone()[0]


def test_only_owners_and_admins_resume_and_they_must_say_why(db, live, act_as, as_admin):
    h = hold(db, live)
    claim(db, live)  # a send held while paused
    assert "only owners and admins" in as_user(db, act_as, as_admin, live["approver"], "select resolve_hold(%s, %s)", (h, "checked the offer"))
    assert "at least 10 characters" in as_user(db, act_as, as_admin, live["owner"], "select resolve_hold(%s, %s)", (h, "ok"))
    assert as_user(db, act_as, as_admin, live["owner"], "select resolve_hold(%s, %s)", (h, "Offer extended to next month")) == "ok"
    paused, = db.execute("select paused_at from campaigns where id = %s", (live["campaign"],)).fetchone()
    status, = db.execute("select status from deliveries where campaign_id = %s", (str(live["campaign"]),)).fetchone()
    assert paused is None and status == "failed"  # back in the retry queue, re-checked before it goes
    assert claim(db, live)[0] == "go"
    note, = db.execute("select details->>'note' from audit_log where action = 'circuit.resumed' and target_id = %s",
                       (str(live["campaign"]),)).fetchone()
    assert note == "Offer extended to next month"


def test_resolving_one_hold_leaves_the_campaign_paused_while_another_is_active(db, live, act_as, as_admin):
    a = hold(db, live, "EXPIRED_OFFER")
    hold(db, live, "INVALID_DESTINATION")
    as_user(db, act_as, as_admin, live["owner"], "select resolve_hold(%s, %s, true)", (a, "The offer was extended already"))
    assert db.execute("select status from campaign_holds where id = %s", (a,)).fetchone()[0] == "false_alarm"
    assert claim(db, live)[0] == "held"


def test_people_stop_and_revoke_only_with_the_right_and_a_reason(db, live, act_as, as_admin):
    assert "only owners, admins and approvers" in as_user(db, act_as, as_admin, live["viewer"],
                                                         "select emergency_stop(%s, %s)", (live["campaign"], "Something is wrong here"))
    assert "at least 10 characters" in as_user(db, act_as, as_admin, live["approver"], "select emergency_stop(%s, %s)", (live["campaign"], "stop"))
    assert as_user(db, act_as, as_admin, live["approver"], "select emergency_stop(%s, %s)",
                   (live["campaign"], "Our supplier just recalled this batch")) == "ok"
    assert as_user(db, act_as, as_admin, live["approver"], "select revoke_approval(%s, %s)",
                   (live["campaign"], "The copy still mentions the old price")) == "ok"
    triggers = {r[0] for r in db.execute("select trigger from campaign_holds where campaign_id = %s", (live["campaign"],))}
    assert triggers == {"MANUAL_STOP", "REVOKED_APPROVAL"} and claim(db, live)[0] == "held"


def test_members_read_holds_nobody_edits_them(db, live, act_as, as_admin):
    hold(db, live)
    count = "select count(*) from campaign_holds where campaign_id = %s"
    act_as(live["viewer"])
    assert db.execute(count, (live["campaign"],)).fetchone()[0] == 1
    act_as(live["outsider"])
    assert db.execute(count, (live["campaign"],)).fetchone()[0] == 0
    as_admin()
    assert "permission denied" in as_user(db, act_as, as_admin, live["owner"],
                                          "update campaign_holds set status = 'resolved' where campaign_id = %s", (live["campaign"],))
    assert "permission denied" in as_user(db, act_as, as_admin, live["owner"],
                                          "select place_hold(%s, 'MANUAL_STOP', 'critical', 'x')", (live["campaign"],))


def test_setting_the_offer_end_needs_a_campaign_right(db, live, act_as, as_admin):
    assert as_user(db, act_as, as_admin, live["owner"], "select set_offer_end(%s, now() + interval '1 day')", (live["campaign"],)) == "ok"
    assert "not allowed" in as_user(db, act_as, as_admin, live["viewer"], "select set_offer_end(%s, null)", (live["campaign"],))


def test_a_pause_racing_a_send_wins_once_it_commits():
    """A worker claims a send while another transaction is placing a hold: the
    claim waits for the pause and then sees it (no stale-state bypass)."""
    try:
        psycopg.connect(DB_URL, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("local Supabase Postgres not running")
    user_id = str(uuid.uuid4())
    with psycopg.connect(DB_URL, autocommit=True) as setup:
        setup.execute("insert into auth.users (id, instance_id, aud, role, email) values (%s, '00000000-0000-0000-0000-000000000000', "
                      "'authenticated', 'authenticated', %s)", (user_id, f"{user_id}@race.test"))
        cid = str(setup.execute("insert into campaigns (idea, domain_category, user_id, status) values ('Race', 'other', %s, "
                                "'awaiting_metrics') returning id", (user_id,)).fetchone()[0])
    result = {}
    try:
        with psycopg.connect(DB_URL) as pauser:
            pauser.execute("select place_hold(%s, 'MANUAL_STOP', 'critical', 'Stop everything now')", (cid,))
            # The pause holds the campaign row; a send arriving now must wait for it.

            def send():
                with psycopg.connect(DB_URL, autocommit=True) as worker:
                    result["verdict"] = worker.execute(
                        "select verdict from claim_delivery(%s, 1, 'bluesky', null, '{}'::jsonb)", (cid,)).fetchone()[0]

            t = threading.Thread(target=send)
            t.start()
            time.sleep(0.5)
            assert "verdict" not in result  # still waiting behind the pause
            pauser.commit()
            t.join(timeout=10)
        assert result["verdict"] == "held"
    finally:
        with psycopg.connect(DB_URL, autocommit=True) as cleanup:
            cleanup.execute("delete from deliveries where campaign_id = %s", (cid,))
            cleanup.execute("delete from campaigns where id = %s", (cid,))
            cleanup.execute("delete from auth.users where id = %s", (user_id,))
