"""The email engine in the database: the per-recipient send log, contacts and
consent, suppression, segments and campaign audiences, and isolation between
organisations."""
import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402

H1, H2 = "a" * 64, "b" * 64


@pytest.fixture
def org(db, new_user, act_as, as_admin):
    owner, marketer, viewer, outsider = new_user(), new_user(), new_user(), new_user()
    act_as(owner)
    org_id = db.execute("select create_organization('Brewline')").fetchone()[0]
    act_as(outsider)
    other = db.execute("select create_organization('Other Co')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'marketer'), (%s, %s, 'viewer')",
               (org_id, marketer, org_id, viewer))
    cid = db.execute("insert into campaigns (idea, domain_category, user_id, org_id, status, current_round) values "
                     "('Coffee', 'food_beverage', %s, %s, 'awaiting_gate_2', 1) returning id", (owner, org_id)).fetchone()[0]
    return {"org": org_id, "other": other, "owner": owner, "marketer": marketer, "viewer": viewer,
            "outsider": outsider, "campaign": str(cid)}


def run(db, act_as, as_admin, user, sql, params=()):
    """Run as a user; returns ("ok", rows) or (first line of the error, None)."""
    act_as(user)
    db.execute("savepoint s")
    try:
        rows = db.execute(sql, params).fetchall()
        db.execute("release savepoint s")
        result = ("ok", rows)
    except psycopg.Error as exc:
        db.execute("rollback to savepoint s")
        result = (str(exc).split("\n")[0], None)
    as_admin()
    return result


def record(db, campaign, rows, round_id=1, channel="email"):
    db.execute("select record_email_sends(%s, %s, %s, %s)", (campaign, round_id, channel, Jsonb(rows)))


class TestSendLog:
    def test_each_recipient_is_logged_once_per_round_and_a_retry_updates_it(self, db, org):
        record(db, org["campaign"], [{"recipient_hash": H1, "status": "sent", "resend_id": "re_1"},
                                     {"recipient_hash": H2, "status": "failed", "error": "rate limited"}])
        record(db, org["campaign"], [{"recipient_hash": H1, "status": "sent", "resend_id": "re_1"},
                                     {"recipient_hash": H2, "status": "sent", "resend_id": "re_2"}])
        rows = db.execute("select recipient_hash, status, resend_id, attempts from email_sends where campaign_id = %s "
                          "order by recipient_hash", (org["campaign"],)).fetchall()
        assert rows == [(H1, "sent", "re_1", 1), (H2, "sent", "re_2", 2)]

    def test_a_logged_send_never_goes_back_to_failed(self, db, org):
        record(db, org["campaign"], [{"recipient_hash": H1, "status": "sent", "resend_id": "re_1"}])
        record(db, org["campaign"], [{"recipient_hash": H1, "status": "failed", "error": "timeout"}])
        assert db.execute("select status from email_sends where recipient_hash = %s", (H1,)).fetchone()[0] == "sent"

    def test_members_read_their_campaigns_log_others_and_users_cannot_write(self, db, org, act_as, as_admin):
        record(db, org["campaign"], [{"recipient_hash": H1, "status": "sent", "resend_id": "re_1"}])
        assert run(db, act_as, as_admin, org["viewer"], "select count(*) from email_sends")[1] == [(1,)]
        assert run(db, act_as, as_admin, org["outsider"], "select count(*) from email_sends")[1] == [(0,)]
        status, _ = run(db, act_as, as_admin, org["owner"], "select record_email_sends(%s, 1, 'email', '[]'::jsonb)",
                        (org["campaign"],))
        assert "permission denied" in status


IMPORT = "select upsert_contacts(%s, %s, %s, %s, %s)"
CONSENT_TEXT = "Everyone in this file opted in to receive marketing email from us."


def import_rows(db, act_as, as_admin, o, rows, user="marketer", source="checkout", note="website checkout, 2025"):
    status, out = run(db, act_as, as_admin, o[user], IMPORT, (o["org"], Jsonb(rows), source, note, CONSENT_TEXT))
    return status, (out[0][0] if out else None)


class TestContacts:
    def test_an_import_adds_subscribed_contacts_with_their_consent_record(self, db, org, act_as, as_admin):
        status, out = import_rows(db, act_as, as_admin, org, [
            {"email": "  Ana@Example.com ", "first_name": "Ana", "tags": ["vip", "coffee"], "attributes": {"orders": 3}},
            {"email": "ben@example.com"}])
        assert status == "ok" and out["added"] == 2 and out["skipped"] == []
        row = db.execute("select email, first_name, tags, status, consent_source, consent_note, consent_text, consent_at is not null "
                         "from contacts where org_id = %s and email = 'ana@example.com'", (org["org"],)).fetchone()
        assert row == ("ana@example.com", "Ana", ["vip", "coffee"], "subscribed", "checkout", "website checkout, 2025", CONSENT_TEXT, True)
        kinds = db.execute("select kind, count(*) from contact_events e join contacts c on c.id = e.contact_id "
                           "where c.org_id = %s group by kind", (org["org"],)).fetchall()
        assert kinds == [("imported", 2)]

    def test_bad_and_duplicate_addresses_are_skipped_with_a_reason(self, db, org, act_as, as_admin):
        _, out = import_rows(db, act_as, as_admin, org, [{"email": "not-an-email"}, {"email": "a@x.io"}, {"email": "A@x.io"}])
        assert out["added"] == 1
        assert sorted(s["reason"] for s in out["skipped"]) == ["duplicate", "invalid"]

    def test_a_second_import_updates_details_but_never_status(self, db, org, act_as, as_admin):
        import_rows(db, act_as, as_admin, org, [{"email": "a@x.io", "tags": ["vip"]}])
        db.execute("update contacts set status = 'unsubscribed' where email = 'a@x.io'")
        _, out = import_rows(db, act_as, as_admin, org, [{"email": "a@x.io", "first_name": "Ana", "tags": ["coffee"],
                                                          "attributes": {"orders": 5}}])
        assert out["updated"] == 1
        row = db.execute("select status, first_name, tags, attributes->>'orders' from contacts where email = 'a@x.io'").fetchone()
        assert row == ("unsubscribed", "Ana", ["vip", "coffee"], "5")

    def test_a_suppressed_address_is_never_added_back(self, db, org, act_as, as_admin):
        db.execute("insert into email_suppressions (org_id, email_hash, reason) values (%s, encode(extensions.digest('gone@x.io', 'sha256'), 'hex'), 'erased')",
                   (org["org"],))
        _, out = import_rows(db, act_as, as_admin, org, [{"email": "Gone@x.io"}])
        assert out["added"] == 0 and out["skipped"] == [{"email": "gone@x.io", "reason": "suppressed"}]

    def test_the_free_plan_caps_contacts(self, db, org, act_as, as_admin):
        db.execute("update plan_limits set max_contacts = 2 where plan = 'free'")
        _, out = import_rows(db, act_as, as_admin, org, [{"email": f"p{i}@x.io"} for i in range(3)])
        assert out["added"] == 2 and out["skipped"] == [{"email": "p2@x.io", "reason": "plan_limit"}]

    def test_an_import_needs_a_source_and_the_attestation_wording(self, db, org, act_as, as_admin):
        status, _ = run(db, act_as, as_admin, org["marketer"], IMPORT, (org["org"], Jsonb([{"email": "a@x.io"}]), "nonsense", None, CONSENT_TEXT))
        assert "consent source" in status
        status, _ = run(db, act_as, as_admin, org["marketer"], IMPORT, (org["org"], Jsonb([{"email": "a@x.io"}]), "checkout", None, ""))
        assert "consent wording" in status

    def test_who_can_see_and_import_addresses(self, db, org, act_as, as_admin):
        import_rows(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        assert import_rows(db, act_as, as_admin, org, [{"email": "b@x.io"}], user="viewer")[0].startswith("only owners, admins and marketers")
        assert run(db, act_as, as_admin, org["marketer"], "select count(*) from contacts")[1] == [(1,)]
        assert run(db, act_as, as_admin, org["viewer"], "select count(*) from contacts")[1] == [(0,)]  # no addresses for viewers
        assert run(db, act_as, as_admin, org["outsider"], "select count(*) from contacts")[1] == [(0,)]
        counts = run(db, act_as, as_admin, org["viewer"], "select contact_counts(%s)", (org["org"],))[1][0][0]
        assert counts["subscribed"] == 1 and counts["total"] == 1 and counts["cap"] == 1000
        assert run(db, act_as, as_admin, org["outsider"], "select contact_counts(%s)", (org["org"],))[0].startswith("not a member")

    def test_users_cannot_write_contacts_directly(self, db, org, act_as, as_admin):
        status, _ = run(db, act_as, as_admin, org["owner"], "insert into contacts (org_id, email, consent_source, consent_text) "
                                                             "values (%s, 'x@x.io', 'manual', 'x') returning id", (org["org"],))
        assert "row-level security" in status or "permission denied" in status

    def test_tag_counts_are_for_every_member_and_carry_no_addresses(self, db, org, act_as, as_admin):
        import_rows(db, act_as, as_admin, org, [{"email": "a@x.io", "tags": ["vip", "coffee"]}, {"email": "b@x.io", "tags": ["coffee"]}])
        assert run(db, act_as, as_admin, org["viewer"], "select * from contact_tags(%s)", (org["org"],))[1] == [("coffee", 2), ("vip", 1)]
        assert run(db, act_as, as_admin, org["outsider"], "select * from contact_tags(%s)", (org["org"],))[0].startswith("not a member")


SAVE = ("select save_email_connection(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")


def connect(db, o, mode="live", key="re_send_only_key_1234", webhook_secret="whsec_abcdef"):
    db.execute(SAVE, (o["org"], mode, key, "hello@brewline.coffee" if mode == "live" else "onboarding@resend.dev", "Brewline",
                      None, "brewline.coffee" if mode == "live" else None, "dom_1" if mode == "live" else None,
                      "ava@example.com" if mode == "sandbox" else None, "wh_1", webhook_secret))


class TestEmailSettings:
    def test_keys_live_in_vault_and_only_the_worker_reads_them(self, db, org, act_as, as_admin):
        connect(db, org)
        row = db.execute("select mode, masked_key, from_email, domain, sending_key_secret_id is not null, webhook_secret_id is not null "
                         "from org_email_settings where org_id = %s", (org["org"],)).fetchone()
        assert row == ("live", "****1234", "hello@brewline.coffee", "brewline.coffee", True, True)
        cfg = db.execute("select email_sending_config(%s)", (org["org"],)).fetchone()[0]
        assert cfg["api_key"] == "re_send_only_key_1234" and cfg["from"] == "Brewline <hello@brewline.coffee>" and cfg["mode"] == "live"
        assert db.execute("select email_webhook_secret(%s)", (org["org"],)).fetchone()[0] == "whsec_abcdef"
        assert "permission denied" in run(db, act_as, as_admin, org["owner"], "select email_sending_config(%s)", (org["org"],))[0]
        assert "permission denied" in run(db, act_as, as_admin, org["owner"], "select email_webhook_secret(%s)", (org["org"],))[0]

    def test_reconnecting_replaces_the_old_secrets(self, db, org):
        connect(db, org, key="re_first_key_1111")
        first = db.execute("select sending_key_secret_id from org_email_settings where org_id = %s", (org["org"],)).fetchone()[0]
        connect(db, org, mode="sandbox", key="re_second_key_2222")
        assert db.execute("select count(*) from vault.secrets where id = %s", (first,)).fetchone()[0] == 0
        cfg = db.execute("select email_sending_config(%s)", (org["org"],)).fetchone()[0]
        assert cfg["api_key"] == "re_second_key_2222" and cfg["mode"] == "sandbox" and cfg["sandbox_to"] == "ava@example.com"

    def test_every_member_sees_the_status_only_managers_see_the_settings(self, db, org, act_as, as_admin):
        connect(db, org)
        status = run(db, act_as, as_admin, org["viewer"], "select email_status(%s)", (org["org"],))[1][0][0]
        assert status["connected"] is True and status["mode"] == "live" and status["domain"] == "brewline.coffee"
        assert "api_key" not in status and "masked_key" not in status
        assert run(db, act_as, as_admin, org["marketer"], "select count(*) from org_email_settings")[1] == [(0,)]
        assert run(db, act_as, as_admin, org["owner"], "select count(*) from org_email_settings")[1] == [(1,)]
        assert run(db, act_as, as_admin, org["outsider"], "select email_status(%s)", (org["org"],))[0].startswith("not a member")
        assert run(db, act_as, as_admin, org["viewer"], "select email_status(%s)", (org["other"],))[0].startswith("not a member")

    def test_managers_set_the_limit_and_window(self, db, org, act_as, as_admin):
        connect(db, org)
        prefs = "select update_email_preferences(%s, %s, %s, %s, %s)"
        assert run(db, act_as, as_admin, org["owner"], prefs, (org["org"], 80, 8, 21, "Asia/Kolkata"))[0] == "ok"
        assert db.execute("select daily_limit, send_window_start, send_window_end, timezone from org_email_settings").fetchone() == (80, 8, 21, "Asia/Kolkata")
        assert run(db, act_as, as_admin, org["marketer"], prefs, (org["org"], 50, 9, 20, "UTC"))[0].startswith("only owners and admins")
        assert "time zone" in run(db, act_as, as_admin, org["owner"], prefs, (org["org"], 50, 9, 20, "Mars/Olympus"))[0]
        assert "window" in run(db, act_as, as_admin, org["owner"], prefs, (org["org"], 50, 20, 9, "UTC"))[0]

    def test_disconnecting_removes_the_secrets(self, db, org, act_as, as_admin):
        connect(db, org)
        secret = db.execute("select sending_key_secret_id from org_email_settings").fetchone()[0]
        assert run(db, act_as, as_admin, org["marketer"], "select disconnect_email(%s)", (org["org"],))[0].startswith("only owners and admins")
        assert run(db, act_as, as_admin, org["owner"], "select disconnect_email(%s)", (org["org"],))[0] == "ok"
        assert db.execute("select count(*) from vault.secrets where id = %s", (secret,)).fetchone()[0] == 0
        assert db.execute("select count(*) from org_email_settings").fetchone()[0] == 0

    def test_organisations_get_a_unique_slug_for_their_sign_up_link(self, db, org, act_as, as_admin, new_user):
        slug = db.execute("select slug from organizations where id = %s", (org["org"],)).fetchone()[0]
        assert slug == "brewline"
        act_as(new_user())
        twin = db.execute("select create_organization('Brewline!')").fetchone()[0]
        as_admin()
        twin_slug = db.execute("select slug from organizations where id = %s", (twin,)).fetchone()[0]
        assert twin_slug.startswith("brewline-") and twin_slug != slug

    def test_the_brand_kit_holds_the_postal_address_and_privacy_link(self, db, org, act_as, as_admin):
        upsert = ("insert into brand_kits (org_id, postal_address, privacy_url) values (%s, %s, %s) "
                  "on conflict (org_id) do update set postal_address = excluded.postal_address, privacy_url = excluded.privacy_url returning org_id")
        assert run(db, act_as, as_admin, org["owner"], upsert, (org["org"], "12 Bean St, Pune 411001", "https://brewline.coffee/privacy"))[0] == "ok"
        assert "violates check constraint" in run(db, act_as, as_admin, org["owner"], upsert, (org["org"], "x", "javascript:alert(1)"))[0]


def people(db, act_as, as_admin, o, rows):
    status, out = import_rows(db, act_as, as_admin, o, rows)
    assert status == "ok", status
    return {e: str(i) for e, i in db.execute("select email, id from contacts where org_id = %s", (o["org"],)).fetchall()}


def segment(db, act_as, as_admin, o, flt, name="Coffee buyers", user="marketer"):
    status, rows = run(db, act_as, as_admin, o[user], "insert into segments (org_id, name, filter) values (%s, %s, %s) returning id",
                       (o["org"], name, Jsonb(flt)))
    assert status == "ok", status
    return str(rows[0][0])


def batch(db, campaign, size):
    return db.execute("select email, first_name, recipient_hash, contact_id from email_next_batch(%s, %s)", (campaign, size)).fetchall()


def freeze_with(db, act_as, as_admin, o, flt):
    seg = segment(db, act_as, as_admin, o, flt)
    assert run(db, act_as, as_admin, o["marketer"], "select set_campaign_segment(%s, %s)", (o["campaign"], seg))[0] == "ok"
    return db.execute("select freeze_campaign_audience(%s)", (o["campaign"],)).fetchone()[0]


class TestSegmentsAndAudience:
    def test_a_segment_counts_only_people_who_can_be_emailed(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [
            {"email": "a@x.io", "tags": ["coffee"], "language": "en", "attributes": {"last_purchase_at": "2026-10-01", "products": ["Cold brew"]}},
            {"email": "b@x.io", "tags": ["coffee", "vip"], "language": "fr"},
            {"email": "c@x.io", "tags": ["tea"]},
            {"email": "d@x.io", "tags": ["coffee"]}])
        db.execute("update contacts set status = 'unsubscribed' where id = %s", (ids["d@x.io"],))

        def count(flt):
            status, rows = run(db, act_as, as_admin, org["viewer"], "select segment_count(%s, %s, %s)", (org["org"], Jsonb(flt), "en"))
            assert status == "ok", status
            return rows[0][0]

        assert count({"tags_any": ["coffee"]}) == 1  # b is French, d unsubscribed
        assert count({"tags_any": ["coffee"], "match_campaign_language": False}) == 2
        assert count({"tags_all": ["coffee", "vip"], "match_campaign_language": False}) == 1
        assert count({"tags_none": ["tea"]}) == 1  # a (c has tea, b is French)
        assert count({}) == 2  # a, and c whose language is unknown
        assert count({"purchased_within_days": 3650, "product_any": ["cold brew"]}) == 1
        assert count({"not_purchased_within_days": 3650, "match_campaign_language": False}) == 2  # b and c never bought
        assert run(db, act_as, as_admin, org["outsider"], "select segment_count(%s, %s, %s)", (org["org"], Jsonb({}), "en"))[0].startswith("not a member")

    def test_viewers_cannot_write_segments(self, db, org, act_as, as_admin):
        status, _ = run(db, act_as, as_admin, org["viewer"], "insert into segments (org_id, name, filter) values (%s, 'x', '{}') returning id", (org["org"],))
        assert "row-level security" in status

    def test_the_audience_is_fixed_at_gate_1_and_batches_never_repeat_anyone(self, db, org, act_as, as_admin):
        people(db, act_as, as_admin, org, [{"email": f"p{i}@x.io", "first_name": f"P{i}", "tags": ["coffee"]} for i in range(5)])
        seg = segment(db, act_as, as_admin, org, {"tags_any": ["coffee"]})
        set_seg = "select set_campaign_segment(%s, %s)"
        assert run(db, act_as, as_admin, org["viewer"], set_seg, (org["campaign"], seg))[0].startswith("only owners, admins and marketers")
        assert run(db, act_as, as_admin, org["marketer"], set_seg, (org["campaign"], seg))[0] == "ok"
        assert db.execute("select freeze_campaign_audience(%s)", (org["campaign"],)).fetchone()[0] == 5
        assert db.execute("select freeze_campaign_audience(%s)", (org["campaign"],)).fetchone()[0] == 5  # only once
        assert run(db, act_as, as_admin, org["marketer"], set_seg, (org["campaign"], None))[0].startswith("the email audience is fixed")
        people(db, act_as, as_admin, org, [{"email": "late@x.io", "tags": ["coffee"]}])  # joins later: not in this campaign
        first = batch(db, org["campaign"], 2)
        assert len(first) == 2 and all(len(r[2]) == 64 for r in first)
        record(db, org["campaign"], [{"recipient_hash": r[2], "contact_id": str(r[3]), "status": "sent", "resend_id": f"re_{i}"}
                                     for i, r in enumerate(first)])
        second = batch(db, org["campaign"], 10)
        assert len(second) == 3 and not {r[0] for r in first} & {r[0] for r in second}
        assert "late@x.io" not in {r[0] for r in first + second}
        progress = run(db, act_as, as_admin, org["viewer"], "select audience_progress(%s)", (org["campaign"],))[1][0][0]
        assert progress == {"total": 5, "emailed": 2, "remaining": 3, "holdout": 0, "excluded": 0, "waiting": 0, "excluded_by": {}}

    def test_people_who_unsubscribe_after_the_freeze_are_skipped(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": "a@x.io"}, {"email": "b@x.io"}])
        freeze_with(db, act_as, as_admin, org, {})
        db.execute("update contacts set status = 'unsubscribed' where id = %s", (ids["a@x.io"],))
        assert [r[0] for r in batch(db, org["campaign"], 10)] == ["b@x.io"]
        assert db.execute("select audience_progress(%s)", (org["campaign"],)).fetchone()[0]["excluded"] == 1

    def test_the_holdout_is_never_in_a_batch(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": "a@x.io"}, {"email": "b@x.io"}])
        freeze_with(db, act_as, as_admin, org, {})
        db.execute("select set_audience_holdout(%s, %s)", (org["campaign"], [ids["a@x.io"]]))
        assert [r[0] for r in batch(db, org["campaign"], 10)] == ["b@x.io"]

    def test_workers_only(self, db, org, act_as, as_admin):
        for sql in ("select freeze_campaign_audience(%s)", "select * from email_next_batch(%s, 5)"):
            assert "permission denied" in run(db, act_as, as_admin, org["owner"], sql, (org["campaign"],))[0]


class TestUnsubscribe:
    def frozen(self, db, act_as, as_admin, org):
        ids = people(db, act_as, as_admin, org, [{"email": "a@x.io", "first_name": "Ana", "language": "fr"}])
        segment_id = segment(db, act_as, as_admin, org, {"match_campaign_language": False})
        run(db, act_as, as_admin, org["marketer"], "select set_campaign_segment(%s, %s)", (org["campaign"], segment_id))
        db.execute("select freeze_campaign_audience(%s)", (org["campaign"],))
        token = db.execute("select unsub_token from campaign_audience where contact_id = %s", (ids["a@x.io"],)).fetchone()[0]
        return ids["a@x.io"], token

    def test_the_token_unsubscribes_and_suppresses_for_good(self, db, org, act_as, as_admin):
        contact, token = self.frozen(db, act_as, as_admin, org)
        assert len(token) == 32
        info = db.execute("select unsubscribe_info(%s)", (token,)).fetchone()[0]
        assert info["brand"] == "Brewline" and info["status"] == "subscribed" and info["language"] == "fr" and "email" not in info
        assert db.execute("select unsubscribe_by_token(%s)", (token,)).fetchone()[0]["status"] == "unsubscribed"
        assert db.execute("select unsubscribe_by_token(%s)", (token,)).fetchone()[0]["status"] == "unsubscribed"  # idempotent
        assert db.execute("select status from contacts where id = %s", (contact,)).fetchone()[0] == "unsubscribed"
        assert db.execute("select count(*) from email_suppressions where org_id = %s and reason = 'unsubscribed'", (org["org"],)).fetchone()[0] == 1
        events = db.execute("select actor from contact_events where contact_id = %s and kind = 'unsubscribed'", (contact,)).fetchall()
        assert events == [("contact",)]
        assert batch(db, org["campaign"], 10) == []

    def test_an_unknown_token_reveals_nothing(self, db, org):
        assert db.execute("select unsubscribe_info(%s)", ("0" * 32,)).fetchone()[0] is None
        assert db.execute("select unsubscribe_by_token(%s)", ("0" * 32,)).fetchone()[0] is None


EVENT = "select record_email_event(%s, %s, %s, %s, %s)"


class TestDeliveryEvents:
    def sent(self, db, act_as, as_admin, org, n=1):
        ids = people(db, act_as, as_admin, org, [{"email": f"p{i}@x.io"} for i in range(n)])
        connect(db, org)
        record(db, org["campaign"], [{"recipient_hash": f"{i:064x}", "contact_id": ids[f"p{i}@x.io"], "status": "sent", "resend_id": f"re_{i}"}
                                     for i in range(n)])
        return ids

    def test_delivered_marks_the_send_and_the_webhook_as_working(self, db, org, act_as, as_admin):
        self.sent(db, act_as, as_admin, org)
        assert db.execute(EVENT, (org["org"], "msg_1", "email.delivered", "re_0", None)).fetchone()[0] == "delivered"
        assert db.execute("select status from email_sends where resend_id = 're_0'").fetchone()[0] == "delivered"
        assert db.execute("select webhook_ok_at is not null from org_email_settings where org_id = %s", (org["org"],)).fetchone()[0]

    def test_the_same_event_twice_counts_once(self, db, org, act_as, as_admin):
        ids = self.sent(db, act_as, as_admin, org)
        db.execute(EVENT, (org["org"], "msg_1", "email.bounced", "re_0", "Transient"))
        assert db.execute(EVENT, (org["org"], "msg_1", "email.bounced", "re_0", "Transient")).fetchone()[0] == "duplicate"
        assert db.execute("select soft_bounces from contacts where id = %s", (ids["p0@x.io"],)).fetchone()[0] == 1

    def test_a_hard_bounce_suppresses_at_once(self, db, org, act_as, as_admin):
        ids = self.sent(db, act_as, as_admin, org)
        assert db.execute(EVENT, (org["org"], "msg_1", "email.bounced", "re_0", "Permanent")).fetchone()[0] == "bounced"
        assert db.execute("select status from contacts where id = %s", (ids["p0@x.io"],)).fetchone()[0] == "bounced"
        assert db.execute("select reason from email_suppressions where org_id = %s", (org["org"],)).fetchone()[0] == "bounced"
        assert db.execute("select status from email_sends where resend_id = 're_0'").fetchone()[0] == "bounced"

    def test_three_soft_bounces_in_a_row_suppress_but_a_delivery_resets_the_count(self, db, org, act_as, as_admin):
        ids = self.sent(db, act_as, as_admin, org)
        for i in range(2):
            db.execute(EVENT, (org["org"], f"s{i}", "email.bounced", "re_0", "Transient"))
        db.execute(EVENT, (org["org"], "d1", "email.delivered", "re_0", None))
        assert db.execute("select soft_bounces, status from contacts where id = %s", (ids["p0@x.io"],)).fetchone() == (0, "subscribed")
        for i in range(3):
            db.execute(EVENT, (org["org"], f"t{i}", "email.bounced", "re_0", "Undetermined"))
        assert db.execute("select status from contacts where id = %s", (ids["p0@x.io"],)).fetchone()[0] == "bounced"

    def test_a_complaint_suppresses_for_good(self, db, org, act_as, as_admin):
        ids = self.sent(db, act_as, as_admin, org)
        assert db.execute(EVENT, (org["org"], "c1", "email.complained", "re_0", None)).fetchone()[0] == "complained"
        assert db.execute("select status from contacts where id = %s", (ids["p0@x.io"],)).fetchone()[0] == "complained"
        assert db.execute("select reason from email_suppressions where org_id = %s", (org["org"],)).fetchone()[0] == "complained"

    def test_events_for_other_email_or_another_organisation_are_ignored(self, db, org, act_as, as_admin):
        self.sent(db, act_as, as_admin, org)
        assert db.execute(EVENT, (org["org"], "x1", "email.bounced", "re_not_ours", "Permanent")).fetchone()[0] == "ignored"
        assert db.execute(EVENT, (org["other"], "x2", "email.bounced", "re_0", "Permanent")).fetchone()[0] == "ignored"
        assert db.execute("select count(*) from email_suppressions").fetchone()[0] == 0

    def test_too_many_complaints_pause_the_brands_email_and_a_manager_resumes_it(self, db, org, act_as, as_admin):
        self.sent(db, act_as, as_admin, org, n=200)
        assert db.execute(EVENT, (org["org"], "c1", "email.complained", "re_0", None)).fetchone()[0] == "paused"  # 1 in 200 = 0.5%
        reason = db.execute("select paused_reason from org_email_settings where org_id = %s", (org["org"],)).fetchone()[0]
        assert "complaint" in reason
        assert run(db, act_as, as_admin, org["marketer"], "select resume_email(%s)", (org["org"],))[0].startswith("only owners and admins")
        assert run(db, act_as, as_admin, org["owner"], "select resume_email(%s)", (org["org"],))[0] == "ok"
        assert db.execute("select paused_reason from org_email_settings where org_id = %s", (org["org"],)).fetchone()[0] is None

    def test_a_small_sample_never_pauses(self, db, org, act_as, as_admin):
        self.sent(db, act_as, as_admin, org, n=10)
        assert db.execute(EVENT, (org["org"], "c1", "email.complained", "re_0", None)).fetchone()[0] == "complained"
        assert db.execute("select paused_reason from org_email_settings where org_id = %s", (org["org"],)).fetchone()[0] is None

    def test_workers_and_the_webhook_only(self, db, org, act_as, as_admin):
        assert "permission denied" in run(db, act_as, as_admin, org["owner"], EVENT, (org["org"], "m", "email.delivered", "re_0", None))[0]


class TestWaitingSends:
    def waiting(self, db, act_as, as_admin, org, n=2, when="now() - interval '1 minute'"):
        ids = people(db, act_as, as_admin, org, [{"email": f"w{i}@x.io"} for i in range(n)])
        connect(db, org)
        record(db, org["campaign"], [{"recipient_hash": f"{i:064x}", "contact_id": ids[f"w{i}@x.io"], "status": "deferred"} for i in range(n)])
        db.execute(f"update email_sends set send_after = {when} where campaign_id = %s", (org["campaign"],))
        return ids

    def test_due_waiting_emails_are_claimed_once(self, db, org, act_as, as_admin):
        self.waiting(db, act_as, as_admin, org)
        due = db.execute("select campaign_id, round_number, channel, recipient_hash, org_id from email_due_deferred(10)").fetchall()
        assert len(due) == 2 and all(str(r[4]) == str(org["org"]) for r in due)
        assert db.execute("select email_due_deferred(10)").fetchall() == []  # claimed (queued) now
        assert {r[0] for r in db.execute("select status from email_sends").fetchall()} == {"queued"}

    def test_not_yet_due_waits(self, db, org, act_as, as_admin):
        self.waiting(db, act_as, as_admin, org, when="now() + interval '2 hours'")
        assert db.execute("select email_due_deferred(10)").fetchall() == []

    def test_someone_who_unsubscribed_meanwhile_is_cancelled_not_sent(self, db, org, act_as, as_admin):
        ids = self.waiting(db, act_as, as_admin, org)
        db.execute("update contacts set status = 'unsubscribed' where id = %s", (ids["w0@x.io"],))
        due = db.execute("select recipient_hash from email_due_deferred(10)").fetchall()
        assert due == [(f"{1:064x}",)]
        assert db.execute("select status from email_sends where contact_id = %s", (ids["w0@x.io"],)).fetchone()[0] == "cancelled"

    def test_a_held_campaign_keeps_its_waiting_emails_a_stopped_one_cancels_them(self, db, org, act_as, as_admin):
        self.waiting(db, act_as, as_admin, org)
        db.execute("update campaigns set paused_at = now() where id = %s", (org["campaign"],))
        assert db.execute("select email_due_deferred(10)").fetchall() == []
        assert {r[0] for r in db.execute("select status from email_sends").fetchall()} == {"deferred"}
        db.execute("update campaigns set paused_at = null, stop_requested = true where id = %s", (org["campaign"],))
        assert {r[0] for r in db.execute("select status from email_sends").fetchall()} == {"cancelled"}

    def test_waiting_people_are_not_remaining_and_shown_as_waiting(self, db, org, act_as, as_admin):
        self.waiting(db, act_as, as_admin, org)
        progress = db.execute("select audience_progress(%s)", (org["campaign"],)).fetchone()[0]
        assert progress["waiting"] == 2

    def test_todays_sends_count_against_the_daily_limit(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": f"t{i}@x.io"} for i in range(3)])
        connect(db, org)
        record(db, org["campaign"], [{"recipient_hash": f"{i:064x}", "contact_id": ids[f"t{i}@x.io"], "status": "sent", "resend_id": f"re_{i}"}
                                     for i in range(2)])
        record(db, org["campaign"], [{"recipient_hash": f"{9:064x}", "contact_id": ids["t2@x.io"], "status": "sent", "resend_id": "re_s",
                                      "sandbox": True}], round_id=2)
        assert db.execute("select email_sent_today(%s)", (org["org"],)).fetchone()[0] == 3
        assert db.execute("select email_sent_today(%s)", (org["other"],)).fetchone()[0] == 0


SIGNUP = "select signup_contact(%s, %s, %s, %s, %s, %s, %s)"
WORDING = "Yes, send me marketing emails from Brewline. I can unsubscribe any time."


def signup(db, slug, email, *, first_name="Ana", language="en", campaign=None, ip="203.0.113.7"):
    return db.execute(SIGNUP, (slug, email, first_name, language, campaign, WORDING, ip)).fetchone()[0]


class TestSignup:
    def test_signing_up_waits_for_the_confirmation_link_then_subscribes_with_tags(self, db, org):
        connect(db, org)
        out = signup(db, "brewline", "Ana@Example.com", campaign=org["campaign"])
        assert out["action"] == "confirm_email" and len(out["token"]) == 32 and out["email"] == "ana@example.com"
        row = db.execute("select status, consent_source, consent_text from contacts where email = 'ana@example.com'").fetchone()
        assert row == ("pending", "signup_form", WORDING)
        done = db.execute("select confirm_contact(%s)", (out["token"],)).fetchone()[0]
        assert done["status"] == "subscribed" and done["brand"] == "Brewline"
        status, tags, confirmed = db.execute("select status, tags, confirmed_at is not null from contacts where email = 'ana@example.com'").fetchone()
        assert status == "subscribed" and confirmed and "signed-up" in tags and any(t.startswith("from:coffee") for t in tags)
        assert db.execute("select confirm_contact(%s)", (out["token"],)).fetchone()[0]["status"] == "subscribed"  # a second click is fine

    def test_a_confirmation_link_expires_after_a_week(self, db, org):
        connect(db, org)
        out = signup(db, "brewline", "late@x.io")
        db.execute("update contacts set confirm_expires_at = now() - interval '1 minute' where email = 'late@x.io'")
        assert db.execute("select confirm_contact(%s)", (out["token"],)).fetchone()[0] is None
        assert db.execute("select status from contacts where email = 'late@x.io'").fetchone()[0] == "pending"

    def test_someone_already_subscribed_gets_no_email(self, db, org, act_as, as_admin):
        connect(db, org)
        import_rows(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        assert signup(db, "brewline", "a@x.io")["action"] == "already"

    def test_someone_who_unsubscribed_can_come_back_only_by_confirming(self, db, org, act_as, as_admin):
        connect(db, org)
        import_rows(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        db.execute("update contacts set status = 'unsubscribed' where email = 'a@x.io'")
        db.execute("insert into email_suppressions (org_id, email_hash, reason) values (%s, email_hash('a@x.io'), 'unsubscribed')", (org["org"],))
        out = signup(db, "brewline", "a@x.io")
        assert out["action"] == "confirm_email"
        assert db.execute("select status from contacts where email = 'a@x.io'").fetchone()[0] == "unsubscribed"  # not until confirmed
        db.execute("select confirm_contact(%s)", (out["token"],))
        assert db.execute("select status from contacts where email = 'a@x.io'").fetchone()[0] == "subscribed"
        assert db.execute("select count(*) from email_suppressions where org_id = %s", (org["org"],)).fetchone()[0] == 0

    def test_a_complaint_or_erasure_is_never_undone_by_the_form(self, db, org):
        connect(db, org)
        db.execute("insert into email_suppressions (org_id, email_hash, reason) values (%s, email_hash('gone@x.io'), 'erased')", (org["org"],))
        assert signup(db, "brewline", "gone@x.io")["action"] == "blocked"
        assert db.execute("select count(*) from contacts where email = 'gone@x.io'").fetchone()[0] == 0

    def test_the_form_is_closed_without_email_connected_and_politely_over_the_cap(self, db, org, act_as, as_admin):
        assert signup(db, "brewline", "a@x.io")["action"] == "not_connected"
        connect(db, org)
        db.execute("update plan_limits set max_contacts = 2 where plan = 'free'")
        import_rows(db, act_as, as_admin, org, [{"email": "x1@x.io"}, {"email": "x2@x.io"}])
        assert signup(db, "brewline", "a@x.io")["action"] == "confirm_email"  # 10% over the cap is still open (2 -> 3 allowed)
        assert signup(db, "brewline", "b@x.io")["action"] == "closed"

    def test_too_many_sign_ups_from_one_address_are_slowed(self, db, org):
        connect(db, org)
        for i in range(5):
            assert signup(db, "brewline", f"s{i}@x.io", ip="198.51.100.9")["action"] == "confirm_email"
        assert signup(db, "brewline", "s9@x.io", ip="198.51.100.9")["action"] == "rate_limited"
        assert signup(db, "brewline", "other@x.io", ip="198.51.100.10")["action"] == "confirm_email"

    def test_the_form_page_learns_the_brand_and_nothing_else(self, db, org):
        connect(db, org)
        info = db.execute("select signup_info(%s)", ("brewline",)).fetchone()[0]
        assert info["brand"] == "Brewline" and info["open"] is True and "api_key" not in info
        assert db.execute("select signup_info(%s)", ("no-such-brand",)).fetchone()[0] is None

    def test_resubscribing_from_an_unsubscribe_link_sends_a_fresh_confirmation(self, db, org, act_as, as_admin):
        contact, token = TestUnsubscribe().frozen(db, act_as, as_admin, org)
        connect(db, org)
        db.execute("select unsubscribe_by_token(%s)", (token,))
        out = db.execute("select resubscribe_by_token(%s)", (token,)).fetchone()[0]
        assert out["action"] == "confirm_email" and out["email"] == "a@x.io"
        db.execute("select confirm_contact(%s)", (out["token"],))
        assert db.execute("select status from contacts where id = %s", (contact,)).fetchone()[0] == "subscribed"

    def test_confirmation_emails_count_against_the_daily_limit(self, db, org):
        connect(db, org)
        db.execute("select record_system_email(%s, 'confirmation')", (org["org"],))
        assert db.execute("select email_sent_today(%s)", (org["org"],)).fetchone()[0] == 1

    def test_workers_only(self, db, org, act_as, as_admin):
        for sql, args in ((SIGNUP, ("brewline", "a@x.io", None, None, None, WORDING, "1.2.3.4")), ("select confirm_contact(%s)", ("0" * 32,))):
            assert "permission denied" in run(db, act_as, as_admin, org["owner"], sql, args)[0]

    def test_campaign_posts_carry_the_sign_up_link_only_while_email_is_connected_and_switched_on(self, db, org, act_as, as_admin):
        link = "select campaign_signup_link(%s)"
        assert db.execute(link, (org["campaign"],)).fetchone()[0] is None  # not connected
        connect(db, org)
        assert db.execute(link, (org["campaign"],)).fetchone()[0] == {"slug": "brewline", "language": "en"}
        assert run(db, act_as, as_admin, org["viewer"], "select set_campaign_signup_link(%s, false)", (org["campaign"],))[0].startswith("only owners")
        assert run(db, act_as, as_admin, org["marketer"], "select set_campaign_signup_link(%s, false)", (org["campaign"],))[0] == "ok"
        assert db.execute(link, (org["campaign"],)).fetchone()[0] is None


PURCHASE = "select record_contact_purchase(%s, %s, %s, %s::numeric, %s, %s::text[], %s::timestamptz)"


class TestEngagement:
    def test_a_click_marks_the_person_engaged_and_is_logged_once_a_day(self, db, org, act_as, as_admin):
        contact, _ = TestUnsubscribe().frozen(db, act_as, as_admin, org)
        token = db.execute("select click_token from campaign_audience where contact_id = %s", (contact,)).fetchone()[0]
        assert len(token) == 32
        assert db.execute("select touch_contact_click(%s)", (token,)).fetchone()[0] is True
        db.execute("select touch_contact_click(%s)", (token,))
        assert db.execute("select last_engaged_at is not null from contacts where id = %s", (contact,)).fetchone()[0]
        assert db.execute("select count(*) from contact_events where contact_id = %s and kind = 'clicked'", (contact,)).fetchone()[0] == 1
        assert db.execute("select touch_contact_click(%s)", ("0" * 32,)).fetchone()[0] is False

    def test_a_purchase_updates_the_contacts_history_once_per_event(self, db, org, act_as, as_admin):
        people(db, act_as, as_admin, org, [{"email": "a@x.io", "attributes": {"orders": 2, "products": ["Espresso"], "lifetime_value": 10}}])
        args = (org["org"], "A@x.io", "order-1", 12.5, "INR", ["Cold brew", "espresso"], "2026-10-20T10:00:00Z")
        assert db.execute(PURCHASE, args).fetchone()[0] == "updated"
        assert db.execute(PURCHASE, args).fetchone()[0] == "duplicate"
        attrs, engaged = db.execute("select attributes, last_engaged_at from contacts where email = 'a@x.io'").fetchone()
        assert attrs["orders"] == 3 and attrs["last_purchase_at"] == "2026-10-20" and attrs["lifetime_value"] == 22.5
        assert attrs["products"] == ["Espresso", "Cold brew"] and engaged is not None
        assert db.execute("select count(*) from contact_events where kind = 'purchased'").fetchone()[0] == 1

    def test_a_purchase_for_someone_not_on_the_list_or_in_another_organisation_changes_nothing(self, db, org, act_as, as_admin):
        people(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        assert db.execute(PURCHASE, (org["org"], "stranger@x.io", "o1", None, None, None, None)).fetchone()[0] == "unknown"
        assert db.execute(PURCHASE, (org["other"], "a@x.io", "o2", None, None, None, None)).fetchone()[0] == "unknown"

    def test_people_inactive_for_two_years_stop_getting_email_until_they_engage(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": "old@x.io", "consent_at": "2024-01-01"}, {"email": "new@x.io"}])
        count = lambda: db.execute("select segment_count(%s, '{}', 'en')", (org["org"],)).fetchone()[0]  # noqa: E731
        assert count() == 1
        assert db.execute("select contact_counts(%s)", (org["org"],)).fetchone()[0]["inactive"] == 1
        db.execute("update contacts set last_engaged_at = now() - interval '3 months' where id = %s", (ids["old@x.io"],))
        assert count() == 2

    def test_an_inactive_person_is_skipped_from_a_fixed_audience(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": "a@x.io"}, {"email": "b@x.io"}])
        freeze_with(db, act_as, as_admin, org, {})
        db.execute("update contacts set consent_at = now() - interval '25 months' where id = %s", (ids["a@x.io"],))
        assert [r[0] for r in batch(db, org["campaign"], 10)] == ["b@x.io"]
        reason = db.execute("select excluded_reason from campaign_audience where contact_id = %s", (ids["a@x.io"],)).fetchone()[0]
        assert reason == "inactive"


class TestPrivacy:
    def test_owners_export_everyone_with_their_consent_history_and_it_is_audited(self, db, org, act_as, as_admin):
        people(db, act_as, as_admin, org, [{"email": "a@x.io", "tags": ["vip"]}, {"email": "b@x.io"}])
        assert run(db, act_as, as_admin, org["marketer"], "select export_contacts(%s)", (org["org"],))[0].startswith("only owners and admins")
        status, rows = run(db, act_as, as_admin, org["owner"], "select export_contacts(%s)", (org["org"],))
        out = rows[0][0]
        assert status == "ok" and sorted(c["email"] for c in out) == ["a@x.io", "b@x.io"]
        a = next(c for c in out if c["email"] == "a@x.io")
        assert a["consent_source"] == "checkout" and a["tags"] == ["vip"] and [e["kind"] for e in a["history"]] == ["imported"]
        assert db.execute("select count(*) from audit_log where action = 'contacts.exported' and org_id = %s", (org["org"],)).fetchone()[0] == 1

    def test_erasing_leaves_only_the_never_email_again_hash(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        record(db, org["campaign"], [{"recipient_hash": "f" * 64, "contact_id": ids["a@x.io"], "status": "sent", "resend_id": "re_1"}])
        assert run(db, act_as, as_admin, org["marketer"], "select erase_contact(%s)", (ids["a@x.io"],))[0].startswith("only owners and admins")
        assert run(db, act_as, as_admin, org["owner"], "select erase_contact(%s)", (ids["a@x.io"],))[0] == "ok"
        assert db.execute("select count(*) from contacts where org_id = %s", (org["org"],)).fetchone()[0] == 0
        assert db.execute("select count(*) from contact_events where org_id = %s", (org["org"],)).fetchone()[0] == 0
        assert db.execute("select reason from email_suppressions where org_id = %s", (org["org"],)).fetchone()[0] == "erased"
        assert db.execute("select count(*) from email_sends where recipient_hash = %s", ("f" * 64,)).fetchone()[0] == 0  # unlinked
        audit = db.execute("select details from audit_log where action = 'contact.erased' and org_id = %s", (org["org"],)).fetchone()[0]
        assert "a@x.io" not in str(audit) and audit["by"] == "member"
        _, out = import_rows(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        assert out["added"] == 0  # never comes back

    def test_another_organisations_owner_cannot_erase_or_export(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        assert run(db, act_as, as_admin, org["outsider"], "select erase_contact(%s)", (ids["a@x.io"],))[0].startswith("only owners and admins")
        assert run(db, act_as, as_admin, org["outsider"], "select export_contacts(%s)", (org["org"],))[0].startswith("only owners and admins")

    def test_people_erase_themselves_from_the_unsubscribe_page(self, db, org, act_as, as_admin):
        contact, token = TestUnsubscribe().frozen(db, act_as, as_admin, org)
        assert db.execute("select erase_by_token(%s)", (token,)).fetchone()[0] == {"status": "erased", "brand": "Brewline"}
        assert db.execute("select count(*) from contacts where id = %s", (contact,)).fetchone()[0] == 0
        audit = db.execute("select details from audit_log where action = 'contact.erased' and org_id = %s", (org["org"],)).fetchone()[0]
        assert audit["by"] == "the person"
        assert db.execute("select erase_by_token(%s)", (token,)).fetchone()[0] is None  # the token died with them

    def test_the_consent_history_is_readable_by_those_who_see_addresses(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        sql = "select kind from contact_events where contact_id = %s"
        assert run(db, act_as, as_admin, org["marketer"], sql, (ids["a@x.io"],))[1] == [("imported",)]
        assert run(db, act_as, as_admin, org["viewer"], sql, (ids["a@x.io"],))[1] == []


class TestAudienceSuggestion:
    def test_the_catalogue_the_ai_sees_has_names_and_counts_only(self, db, org, act_as, as_admin):
        people(db, act_as, as_admin, org, [
            {"email": "a@x.io", "tags": ["coffee"], "language": "en", "attributes": {"products": ["Cold brew"], "country": "India",
                                                                                     "last_purchase_at": "2026-10-01"}},
            {"email": "b@x.io", "tags": ["coffee", "vip"], "attributes": {"products": ["cold brew", "Beans"]}}])
        cat = db.execute("select contact_catalog(%s)", (org["org"],)).fetchone()[0]
        assert cat["subscribed"] == 2
        assert cat["tags"] == [{"name": "coffee", "people": 2}, {"name": "vip", "people": 1}]
        assert {"name": "cold brew", "people": 2} in cat["products"] and cat["countries"] == [{"name": "india", "people": 1}]
        assert cat["purchased_within"]["365"] >= 1
        assert "@" not in str(cat)
        assert "permission denied" in run(db, act_as, as_admin, org["owner"], "select contact_catalog(%s)", (org["org"],))[0]

    def test_using_the_suggestion_makes_it_the_campaigns_segment_until_gate_1(self, db, org, act_as, as_admin):
        db.execute("update campaigns set email_suggestion = %s where id = %s",
                   (Jsonb({"filter": {"tags_any": ["coffee"]}, "reason": "Coffee buyers fit the commuter persona.", "people": 2}), org["campaign"]))
        use = "select accept_email_suggestion(%s)"
        assert run(db, act_as, as_admin, org["viewer"], use, (org["campaign"],))[0].startswith("only owners, admins and marketers")
        status, rows = run(db, act_as, as_admin, org["marketer"], use, (org["campaign"],))
        assert status == "ok"
        seg = db.execute("select name, filter, org_id from segments where id = %s", (rows[0][0],)).fetchone()
        assert seg[0].startswith("Suggested: Coffee") and seg[1] == {"tags_any": ["coffee"]} and str(seg[2]) == str(org["org"])
        assert str(db.execute("select segment_id from campaigns where id = %s", (org["campaign"],)).fetchone()[0]) == str(rows[0][0])
        db.execute("select freeze_campaign_audience(%s)", (org["campaign"],))
        assert run(db, act_as, as_admin, org["marketer"], use, (org["campaign"],))[0].startswith("the email audience is fixed")


class TestApiContacts:
    def test_the_api_erases_by_address_and_an_unknown_address_is_still_never_added(self, db, org, act_as, as_admin):
        people(db, act_as, as_admin, org, [{"email": "a@x.io"}])
        assert db.execute("select erase_contact_by_email(%s, %s)", (org["org"], "A@x.io")).fetchone()[0] is True
        assert db.execute("select erase_contact_by_email(%s, %s)", (org["org"], "never@x.io")).fetchone()[0] is False
        assert db.execute("select count(*) from email_suppressions where org_id = %s and reason = 'erased'", (org["org"],)).fetchone()[0] == 2
        _, out = import_rows(db, act_as, as_admin, org, [{"email": "never@x.io"}])
        assert out["added"] == 0
        audit = db.execute("select details from audit_log where action = 'contact.erased' and org_id = %s", (org["org"],)).fetchone()[0]
        assert audit["by"] == "api"

    def test_the_api_imports_with_its_own_consent_record_as_the_service(self, db, org):
        out = db.execute("select upsert_contacts(%s, %s, 'api', 'shop sync', 'Opted in at checkout on brewline.coffee')",
                         (org["org"], Jsonb([{"email": "a@x.io", "tags": ["vip"]}]))).fetchone()[0]
        assert out["added"] == 1
        assert db.execute("select consent_source, actor from contacts c join contact_events e on e.contact_id = c.id").fetchone() == ("api", "api")


class TestResults:
    def test_each_rounds_email_results_for_members(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": f"r{i}@x.io"} for i in range(4)])
        rows = [{"recipient_hash": f"{i:064x}", "contact_id": ids[f"r{i}@x.io"], "status": "sent", "resend_id": f"re_{i}"} for i in range(3)]
        record(db, org["campaign"], rows)
        record(db, org["campaign"], [{"recipient_hash": f"{9:064x}", "contact_id": ids["r3@x.io"], "status": "deferred",
                                      "send_after": "2030-01-01T00:00:00Z"}], round_id=2)
        db.execute("update email_sends set status = 'delivered' where resend_id = 're_0'")
        db.execute("update email_sends set status = 'bounced' where resend_id = 're_1'")
        stats = run(db, act_as, as_admin, org["viewer"], "select * from email_round_stats(%s)", (org["campaign"],))[1]
        assert stats == [(1, "email", 3, 1, 1, 0, 0, False), (2, "email", 0, 0, 0, 0, 1, False)]
        assert run(db, act_as, as_admin, org["outsider"], "select * from email_round_stats(%s)", (org["campaign"],))[0].startswith("not a member")

    def test_progress_says_why_people_left_the_audience(self, db, org, act_as, as_admin):
        ids = people(db, act_as, as_admin, org, [{"email": "a@x.io"}, {"email": "b@x.io"}, {"email": "c@x.io"}])
        freeze_with(db, act_as, as_admin, org, {})
        db.execute("update contacts set status = 'unsubscribed' where id = %s", (ids["a@x.io"],))
        db.execute("update contacts set consent_at = now() - interval '25 months' where id = %s", (ids["b@x.io"],))
        batch(db, org["campaign"], 10)
        progress = db.execute("select audience_progress(%s)", (org["campaign"],)).fetchone()[0]
        assert progress["excluded"] == 2 and progress["excluded_by"] == {"unsubscribed": 1, "inactive": 1}

    def test_a_test_email_counts_against_the_daily_limit(self, db, org):
        connect(db, org)
        db.execute("select record_system_email(%s, 'test')", (org["org"],))
        assert db.execute("select email_sent_today(%s)", (org["org"],)).fetchone()[0] == 1
