"""The ad-images bucket: private, readable only by people who can view the campaign."""
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")


def _stored_ad(db, owner: str) -> tuple[str, str]:
    campaign = db.execute(
        "insert into campaigns (idea, domain_category, user_id) values ('Light packs', 'other', %s) returning id", (owner,)
    ).fetchone()[0]
    path = f"{campaign}/round-1.jpg"
    db.execute("insert into storage.objects (bucket_id, name, owner) values ('ad-images', %s, null)", (path,))
    return str(campaign), path


def test_bucket_is_private_and_iterations_point_at_the_ad(db):
    assert db.execute("select public from storage.buckets where id = 'ad-images'").fetchone()[0] is False
    cols = {r[0] for r in db.execute("select column_name from information_schema.columns where table_name = 'iterations'")}
    assert "image_path" in cols


def test_only_campaign_viewers_can_read_the_ad(db, new_user, act_as):
    alice, bob = new_user(), new_user()
    _, path = _stored_ad(db, alice)
    count = "select count(*) from storage.objects where bucket_id = 'ad-images' and name = %s"
    act_as(alice)
    assert db.execute(count, (path,)).fetchone()[0] == 1
    act_as(bob)
    assert db.execute(count, (path,)).fetchone()[0] == 0


def test_odd_paths_are_never_readable(db, new_user, act_as):
    alice = new_user()
    db.execute("insert into storage.objects (bucket_id, name) values ('ad-images', %s)", (f"not-a-campaign/{uuid.uuid4()}.jpg",))
    act_as(alice)
    assert db.execute("select count(*) from storage.objects where bucket_id = 'ad-images' and name like 'not-a-campaign/%'").fetchone()[0] == 0


def test_members_cannot_upload_ads_themselves(db, new_user, act_as):
    alice = new_user()
    campaign = db.execute(
        "insert into campaigns (idea, domain_category, user_id) values ('i', 'other', %s) returning id", (alice,)
    ).fetchone()[0]
    act_as(alice)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into storage.objects (bucket_id, name) values ('ad-images', %s)", (f"{campaign}/round-9.jpg",))


def test_iterations_keep_the_on_image_words_and_repaint_count(db):
    cols = {r[0] for r in db.execute("select column_name from information_schema.columns where table_name = 'iterations'")}
    assert {"headline", "cta", "image_version"} <= cols
    assert "logo_path" in {r[0] for r in db.execute("select column_name from information_schema.columns where table_name = 'brand_kits'")}


def test_members_cannot_reset_the_repaint_count_themselves(db, new_user, act_as, as_admin):
    """Only the worker (service role) writes image_version, so the 5-per-round cap holds."""
    alice = new_user()
    campaign = db.execute(
        "insert into campaigns (idea, domain_category, user_id) values ('i', 'other', %s) returning id", (alice,)
    ).fetchone()[0]
    db.execute("insert into iterations (campaign_id, user_id, round_number, image_version) values (%s, %s, 1, 5)", (campaign, alice))
    act_as(alice)
    db.execute("savepoint s")
    try:
        db.execute("update iterations set image_version = 0 where campaign_id = %s", (campaign,))
    except psycopg.errors.InsufficientPrivilege:
        db.execute("rollback to savepoint s")
    as_admin()
    assert db.execute("select image_version from iterations where campaign_id = %s", (campaign,)).fetchone()[0] == 5


@pytest.fixture
def org_with_roles(db, new_user, act_as, as_admin):
    owner, viewer, outsider = new_user(), new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'viewer')", (org, viewer))
    return str(org), owner, viewer, outsider


def _upload(db, path):
    db.execute("insert into storage.objects (bucket_id, name) values ('brand-logos', %s)", (path,))


def test_logo_bucket_is_private(db):
    assert db.execute("select public from storage.buckets where id = 'brand-logos'").fetchone()[0] is False


def test_managers_upload_logos_viewers_and_outsiders_cannot(db, org_with_roles, act_as):
    org, owner, viewer, outsider = org_with_roles
    act_as(owner)
    _upload(db, f"{org}/logo-1.png")
    for who in (viewer, outsider):
        act_as(who)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("savepoint s")
            try:
                _upload(db, f"{org}/logo-2.png")
            finally:
                db.execute("rollback to savepoint s")


def test_members_see_the_logo_outsiders_do_not(db, org_with_roles, act_as):
    org, owner, viewer, outsider = org_with_roles
    act_as(owner)
    _upload(db, f"{org}/logo-1.png")
    count = "select count(*) from storage.objects where bucket_id = 'brand-logos' and name = %s"
    act_as(viewer)
    assert db.execute(count, (f"{org}/logo-1.png",)).fetchone()[0] == 1
    act_as(outsider)
    assert db.execute(count, (f"{org}/logo-1.png",)).fetchone()[0] == 0


def test_logos_outside_an_org_folder_are_refused(db, org_with_roles, act_as):
    _, owner, _, _ = org_with_roles
    act_as(owner)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _upload(db, "anywhere/logo.png")
