"""Product photos: a private bucket where each user uploads and reads only their
own folder, plus the campaign and iteration columns the ad templates use."""
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")


def _cols(db, table: str) -> set[str]:
    return {r[0] for r in db.execute("select column_name from information_schema.columns where table_name = %s", (table,))}


def test_campaigns_and_iterations_keep_the_product_and_template(db):
    assert {"product_image_path", "product_tagline"} <= _cols(db, "campaigns")
    assert {"template", "ad_slots"} <= _cols(db, "iterations")
    assert db.execute("select public from storage.buckets where id = 'product-photos'").fetchone()[0] is False


def test_a_tagline_is_at_most_80_characters(db, new_user):
    owner = new_user()
    db.execute("savepoint s")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into campaigns (idea, domain_category, user_id, product_tagline) values ('i', 'other', %s, %s)",
            (owner, "x" * 81),
        )
    db.execute("rollback to savepoint s")
    db.execute(
        "insert into campaigns (idea, domain_category, user_id, product_tagline) values ('i', 'other', %s, %s)", (owner, "x" * 80)
    )


def test_users_upload_and_read_only_their_own_photos(db, new_user, act_as):
    alice, bob = new_user(), new_user()
    path = f"{alice}/{uuid.uuid4()}.jpg"
    act_as(alice)
    db.execute("insert into storage.objects (bucket_id, name) values ('product-photos', %s)", (path,))
    count = "select count(*) from storage.objects where bucket_id = 'product-photos' and name = %s"
    assert db.execute(count, (path,)).fetchone()[0] == 1
    act_as(bob)
    assert db.execute(count, (path,)).fetchone()[0] == 0


def test_nobody_uploads_into_someone_elses_folder(db, new_user, act_as):
    alice, bob = new_user(), new_user()
    act_as(bob)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into storage.objects (bucket_id, name) values ('product-photos', %s)", (f"{alice}/{uuid.uuid4()}.jpg",))
