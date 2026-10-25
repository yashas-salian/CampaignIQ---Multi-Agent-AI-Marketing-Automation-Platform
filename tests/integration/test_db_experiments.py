"""Proof-of-impact experiments in the database: who can declare one, the
pre-registration lock, assignments that never move, conversions matched by
token or hashed address and counted once, the final result written once, and
who can read what."""
import hashlib

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402

DECLARE = "select declare_experiment(%s, %s, %s, %s::numeric)"
HYPOTHESIS = "Emailing commuters raises qualified sign-ups"


@pytest.fixture
def org(db, new_user, act_as, as_admin):
    owner, marketer, viewer, outsider = new_user(), new_user(), new_user(), new_user()
    act_as(owner)
    org_id = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'marketer'), (%s, %s, 'viewer')",
               (org_id, marketer, org_id, viewer))
    cid = db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id, status, email_to) "
        "values ('Coffee', 'other', %s, %s, 'awaiting_gate_2', array['a@x.io','b@x.io','c@x.io']) returning id",
        (owner, org_id),
    ).fetchone()[0]
    return {"org": org_id, "owner": owner, "marketer": marketer, "viewer": viewer, "outsider": outsider, "campaign": cid}


def as_user(db, act_as, as_admin, user, sql, params):
    act_as(user)
    db.execute("savepoint s")
    try:
        row = db.execute(sql, params).fetchone()
        db.execute("release savepoint s")
        result = ("ok", row[0] if row else None)
    except psycopg.Error as exc:
        db.execute("rollback to savepoint s")
        result = (str(exc).split("\n")[0], None)
    as_admin()
    return result


def declared(db, act_as, as_admin, c, metric="qualified_signup_rate", share=0.2):
    status, eid = as_user(db, act_as, as_admin, c["marketer"], DECLARE, (c["campaign"], HYPOTHESIS, metric, share))
    assert status == "ok", status
    return eid


def start(db, eid, units):
    total = db.execute("select start_experiment(%s, %s)", (eid, Jsonb(units))).fetchone()[0]
    rows = db.execute("select unit_hash, arm, token from experiment_assignments where experiment_id = %s", (eid,)).fetchall()
    assert total == len(rows)
    return {r[0]: (r[1], r[2]) for r in rows}


def test_declaring_needs_the_right_an_audience_and_a_metric_that_fits(db, org, act_as, as_admin):
    assert "not allowed" in as_user(db, act_as, as_admin, org["viewer"], DECLARE, (org["campaign"], HYPOTHESIS, "conversion_rate", 0.2))[0]
    # A control group can't click: click-through is only for A vs B.
    assert "experiments_metric_fits_design" in as_user(db, act_as, as_admin, org["marketer"], DECLARE,
                                                       (org["campaign"], HYPOTHESIS, "click_through_rate", 0.2))[0]
    assert "turn on the A/B test" in as_user(db, act_as, as_admin, org["marketer"], DECLARE,
                                              (org["campaign"], HYPOTHESIS, "conversion_rate", 0))[0]
    db.execute("update campaigns set email_to = null where id = %s", (org["campaign"],))
    assert "email audience" in as_user(db, act_as, as_admin, org["marketer"], DECLARE, (org["campaign"], HYPOTHESIS, "conversion_rate", 0.2))[0]


def test_the_design_is_editable_until_the_first_send_then_locked(db, org, act_as, as_admin):
    eid = declared(db, act_as, as_admin, org)
    assert declared(db, act_as, as_admin, org, share=0.3) == eid  # changed before it started
    start(db, eid, [{"unit_hash": "h1", "arm": "control"}])
    assert "locked" in as_user(db, act_as, as_admin, org["owner"], DECLARE, (org["campaign"], HYPOTHESIS, "conversion_rate", 0.1))[0]
    assert "runs to its predeclared end" in as_user(db, act_as, as_admin, org["owner"], "select withdraw_experiment(%s)", (org["campaign"],))[0]
    db.execute("savepoint s")
    with pytest.raises(psycopg.Error, match="locked"):  # not even a worker can rewrite it
        db.execute("update experiments set min_effect = 0.5 where id = %s", (eid,))
    db.execute("rollback to savepoint s")
    started, analysis = db.execute("select started_at, analysis_at - started_at from experiments where id = %s", (eid,)).fetchone()
    assert started is not None and analysis.days == 14 + 7


def test_no_experiment_after_emails_already_went_out(db, org, act_as, as_admin):
    db.execute("insert into deliveries (campaign_id, round_number, channel, payload, status) values (%s, 1, 'email', '{}', 'sent')",
               (str(org["campaign"]),))
    assert "before the first send" in as_user(db, act_as, as_admin, org["marketer"], DECLARE, (org["campaign"], HYPOTHESIS, "conversion_rate", 0.2))[0]


def test_assignments_never_move(db, org, act_as, as_admin):
    eid = declared(db, act_as, as_admin, org)
    first = start(db, eid, [{"unit_hash": "h1", "arm": "control"}, {"unit_hash": "h2", "arm": "treatment"}])
    # A retry (or a buggy caller) proposing other arms changes nothing; a new address is added.
    again = start(db, eid, [{"unit_hash": "h1", "arm": "treatment"}, {"unit_hash": "h3", "arm": "treatment"}])
    assert again["h1"] == first["h1"] and again["h2"] == first["h2"] and again["h3"][0] == "treatment"
    assert len({t for _, t in again.values()}) == 3


def test_conversions_match_by_token_or_address_and_count_once(db, org, act_as, as_admin):
    eid = declared(db, act_as, as_admin, org)
    control_hash = hashlib.sha256(f"{eid}:b@x.io".encode()).hexdigest()
    units = start(db, eid, [{"unit_hash": "ha", "arm": "treatment"}, {"unit_hash": control_hash, "arm": "control"}])
    conv = "select matched, arm, duplicate from record_conversion(%s, %s, now(), %s, %s, true, 12.5, 'usd')"
    assert db.execute(conv, (eid, "ord-1", units["ha"][1], None)).fetchone() == (True, "treatment", False)
    assert db.execute(conv, (eid, "ord-1", units["ha"][1], None)).fetchone() == (True, "treatment", True)  # a retried postback
    assert db.execute(conv, (eid, "ord-2", None, control_hash)).fetchone() == (True, "control", False)  # no link: by address
    assert db.execute(conv, (eid, "ord-3", None, "nobody")).fetchone() == (False, None, False)
    rows = db.execute("select arm, currency from experiment_events where experiment_id = %s and kind = 'conversion' order by external_id",
                      (eid,)).fetchall()
    assert rows == [("treatment", "USD"), ("control", "USD"), (None, "USD")]
    assert db.execute("select record_click(%s, 1)", (units["ha"][1],)).fetchone()[0] == "treatment"
    assert db.execute("select record_exposures(%s, 1, array['ha','ha'])", (eid,)).fetchone()[0] == 1
    assert db.execute("select record_exposures(%s, 1, array['ha'])", (eid,)).fetchone()[0] == 0  # once per round


def test_the_final_result_is_written_once(db, org, act_as, as_admin):
    eid = declared(db, act_as, as_admin, org)
    start(db, eid, [{"unit_hash": "h1", "arm": "control"}])
    db.execute("select save_impact(%s, %s, 'COLLECTING', false)", (eid, Jsonb({"status": "COLLECTING"})))
    db.execute("select save_impact(%s, %s, 'POSITIVE_IMPACT', true)",
               (eid, Jsonb({"status": "POSITIVE_IMPACT", "reason": "INTERVAL_ABOVE_ZERO", "estimate": {"absolute_lift": 0.02}})))
    db.execute("select save_impact(%s, %s, 'INCONCLUSIVE', true)", (eid, Jsonb({"status": "INCONCLUSIVE"})))
    status, result_status = db.execute("select status, result_status from experiments where id = %s", (eid,)).fetchone()
    assert (status, result_status) == ("completed", "POSITIVE_IMPACT")
    assert db.execute("select count(*) from audit_log where action = 'experiment.concluded' and target_id = %s",
                      (str(org["campaign"]),)).fetchone()[0] == 1


def test_the_campaign_finishing_early_brings_the_analysis_forward(db, org, act_as, as_admin):
    eid = declared(db, act_as, as_admin, org)
    start(db, eid, [{"unit_hash": "h1", "arm": "control"}])
    db.execute("select save_impact(%s, '{}'::jsonb, 'COLLECTING', false, now() + interval '2 days')", (eid,))
    gap = db.execute("select analysis_at - ends_at, ends_at - started_at from experiments where id = %s", (eid,)).fetchone()
    assert gap[0].days == 7 and gap[1].days == 2


def test_members_read_the_experiment_but_never_the_tokens_or_raw_events(db, org, act_as, as_admin):
    eid = declared(db, act_as, as_admin, org)
    start(db, eid, [{"unit_hash": "h1", "arm": "control"}])
    act_as(org["viewer"])
    assert db.execute("select count(*) from experiments where id = %s", (eid,)).fetchone()[0] == 1
    act_as(org["outsider"])
    assert db.execute("select count(*) from experiments where id = %s", (eid,)).fetchone()[0] == 0
    as_admin()
    for table in ("experiment_assignments", "experiment_events"):
        assert "permission denied" in as_user(db, act_as, as_admin, org["owner"], f"select count(*) from {table}", ())[0]
    assert "permission denied" in as_user(db, act_as, as_admin, org["owner"], "select record_conversion(%s, 'x', now())", (eid,))[0]
    assert "permission denied" in as_user(db, act_as, as_admin, org["owner"], "update experiments set result = null where id = %s", (eid,))[0]


def test_withdrawing_before_the_start(db, org, act_as, as_admin):
    declared(db, act_as, as_admin, org)
    assert as_user(db, act_as, as_admin, org["marketer"], "select withdraw_experiment(%s)", (org["campaign"],))[0] == "ok"
    assert db.execute("select count(*) from experiments where campaign_id = %s", (org["campaign"],)).fetchone()[0] == 0
