"""The finished ad after the layout step: brand logo, email embedding, Gate 2's
"New picture" job and the gate sending the repainted ad."""
import base64
import io

import pytest
from PIL import Image

from src.capabilities import distribution
from src.tools.ad_composer import LOGO_CORNERS, compose_ad


def _picture(color=(40, 120, 200), size=(1024, 1024)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def _logo() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (400, 100), (220, 0, 0, 255)).save(out, format="PNG")
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


class TestLogo:
    def _red_near(self, ad: Image.Image, corner: str) -> bool:
        w, h = ad.size
        box = {
            "top-left": (0, 0, w // 3, h // 5), "bottom-right": (2 * w // 3, 4 * h // 5, w, h),
        }[corner]
        return any(r > 180 and g < 60 and b < 60 for r, g, b in ad.crop(box).getdata())

    @pytest.mark.parametrize("style", list(LOGO_CORNERS))
    def test_logo_sits_in_the_corner_the_layout_leaves_free(self, style):
        ad = _open(compose_ad(_picture(), "Fresh every day", "Order", style=style, logo_bytes=_logo()))
        corner = LOGO_CORNERS[style]
        other = "bottom-right" if corner == "top-left" else "top-left"
        assert self._red_near(ad, corner) and not self._red_near(ad, other)

    def test_logo_alone_still_appears_and_bad_logo_bytes_are_ignored(self):
        ad = _open(compose_ad(_picture(), logo_bytes=_logo()))
        assert self._red_near(ad, "top-left")
        assert compose_ad(_picture(), "Hi", "Go", logo_bytes=b"not an image") == compose_ad(_picture(), "Hi", "Go")

    def test_brand_logo_never_raises(self, monkeypatch):
        from src.capabilities import brand

        assert brand.brand_logo(None) is None and brand.brand_logo(brand.BrandKit()) is None

        def boom(*a):
            raise RuntimeError("storage down")

        monkeypatch.setattr("src.db.supabase_client.download_object", boom)
        assert brand.brand_logo(brand.BrandKit(logo_path="o/logo-1.png")) is None


class TestEmailImage:
    @pytest.fixture(autouse=True)
    def live(self, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "false")  # really "send" (to the fakes below)

    def test_the_ad_is_embedded_inline_and_links_to_the_cta(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(distribution, "send_email", lambda to, subject, html, **k: sent.update(html=html, **k) or "em_1")
        distribution.send_campaign_email(
            "c1", 1, ["a@x.io"], "Hi", "<p>copy</p>", cta_url="https://shop.io", image_bytes=b"jpg", image_alt='Say "hi"',
        )
        assert sent["image_bytes"] == b"jpg"
        assert '<a href="https://shop.io"><img src="cid:ad-image"' in sent["html"]
        assert 'alt="Say &quot;hi&quot;"' in sent["html"]
        assert sent["html"].index("cid:ad-image") < sent["html"].index("copy")  # image on top

    def test_a_template_placeholder_decides_where_the_image_goes(self):
        html = distribution.with_ad_image("<h1>Hello</h1>{{image}}<p>body</p>", "alt", None)
        assert html.startswith("<h1>Hello</h1><img src=\"cid:ad-image\"") and "{{image}}" not in html

    def test_no_image_means_no_tag_and_no_attachment(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(distribution, "send_email", lambda to, subject, html, **k: sent.update(html=html, **k) or "em_1")
        distribution.send_campaign_email("c1", 1, ["a@x.io"], "Hi", "<p>copy</p>")
        assert "cid:" not in sent["html"] and not sent.get("image_bytes")

    def test_a_retried_email_still_carries_its_image(self, monkeypatch):
        sent = []
        monkeypatch.setattr(distribution, "send_email", lambda to, subject, html, **k: sent.append(k) or "em_2")
        payload = {"to": ["a@x.io"], "subject": "Hi", "html": '<img src="cid:ad-image">', "image_base64": base64.b64encode(b"jpg").decode()}
        assert distribution.resend_from_payload("email", "c9", 3, payload, "u1") == "em_2"
        assert sent[0]["image_bytes"] == b"jpg"

    def test_resend_attachment_shape(self, monkeypatch):
        from src.tools import resend_client

        calls = []
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "ads@x.io")
        monkeypatch.setattr(resend_client.resend.Emails, "send", lambda params: calls.append(params) or {"id": "e1"})
        resend_client.send_email(["a@x.io"], "Hi", "<p>x</p>", image_bytes=b"jpg")
        resend_client.send_email(["a@x.io"], "Hi", "<p>x</p>")
        attachment = calls[0]["attachments"][0]
        assert attachment["content_id"] == "ad-image" and base64.b64decode(attachment["content"]) == b"jpg"
        assert "attachments" not in calls[1]


class _Query:
    def __init__(self, client, table):
        self.client, self.table, self.filters, self.patch = client, table, {}, None

    def select(self, *a):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def maybe_single(self):
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def execute(self):
        if self.patch is not None:
            self.client.updates.append((self.table, self.filters, self.patch))
            return type("R", (), {"data": []})()
        row = self.client.rows.get(self.table)
        return type("R", (), {"data": row})() if row is not None else None


class _Client:
    def __init__(self, rows):
        self.rows, self.updates = rows, []

    def table(self, name):
        return _Query(self, name)


class TestNewPictureJob:
    @pytest.fixture
    def job(self, monkeypatch):
        from src.scheduler import run_capability

        def make(role="approver", status="awaiting_gate_2", current_round=1, version=0):
            client = _Client({
                "campaigns": {"org_id": "o1", "status": status, "current_round": current_round},
                "memberships": {"role": role} if role else None,
                "iterations": {
                    "image_prompt": "a barista", "headline": "Ready before you are", "cta": "Order ahead",
                    "image_style": "humor_meme", "image_version": version,
                },
            })
            monkeypatch.setattr(run_capability, "get_client", lambda: client)
            uploads = []
            monkeypatch.setattr("src.db.supabase_client.upload_ad_image", lambda c, r, data: uploads.append(data) or f"{c}/round-{r}.jpg")
            monkeypatch.setattr("src.capabilities.brand.brand_kit_for_campaign", lambda cid: None)
            prompts = []

            class Images:
                def generate_image(self, prompt):
                    prompts.append(prompt)
                    return _picture()

            monkeypatch.setattr("src.providers.registry.get_image_generator", lambda user_id=None: Images())
            return run_capability._run_ad_image, client, uploads, prompts

        return make

    def test_repaints_stores_and_bumps_the_version(self, job):
        run, client, uploads, prompts = job(version=2)
        result = run({"campaign_id": "c1", "round": 1}, "u1")
        assert result == {"campaign_id": "c1", "round": 1, "image_version": 3}
        assert prompts[0].startswith("a barista") and "no text" in prompts[0]
        assert _open(uploads[0]).size == (1080, 1080)
        assert client.updates == [("iterations", {"campaign_id": "c1", "round_number": 1}, {"image_path": "c1/round-1.jpg", "image_version": 3})]

    @pytest.mark.parametrize("role", [None, "viewer", "marketer"])
    def test_only_approvers(self, job, role):
        run, client, uploads, _ = job(role=role)
        with pytest.raises(PermissionError):
            run({"campaign_id": "c1", "round": 1}, "u1")
        assert not uploads and not client.updates

    @pytest.mark.parametrize("kwargs", [{"status": "running"}, {"current_round": 2}, {"version": 5}])
    def test_only_at_gate_2_for_the_current_round_and_within_the_cap(self, job, kwargs):
        run, client, uploads, _ = job(**kwargs)
        with pytest.raises(ValueError):
            run({"campaign_id": "c1", "round": 1}, "u1")
        assert not uploads and not client.updates

    def test_it_is_registered(self):
        from src.scheduler.run_capability import CAPABILITY_DISPATCH

        assert "ad_image" in CAPABILITY_DISPATCH


class TestGate2SendsTheRepaint:
    @pytest.fixture
    def gate(self, monkeypatch):
        from src.capabilities.creative import Creative
        from src.graph.nodes import human_gate

        for name in ("create_pending_gate", "update_campaign_status", "notify_gate_opened"):
            monkeypatch.setattr(human_gate, name, lambda *a, **k: None)
        monkeypatch.setattr(human_gate, "interrupt", lambda payload: {"decision": "approve"})
        creative = Creative(copy_text="Copy", image_prompt="p", image_bytes=b"original", image_style="s", copy_tone="t", arm_index=0)

        def run(iteration, download=lambda bucket, path: b"repainted"):
            monkeypatch.setattr(human_gate, "get_iteration", lambda *a: iteration)
            monkeypatch.setattr(human_gate, "download_object", download)
            return human_gate.gate_2_node({"campaign_id": "c1", "user_id": "u1", "round_id": 1, "creative": creative})

        return run

    def test_a_repainted_ad_replaces_the_original(self, gate):
        update = gate({"copy_text": "Copy", "image_path": "c1/round-1.jpg", "image_version": 1})
        assert update["creative"].image_bytes == b"repainted"

    def test_no_repaint_keeps_the_original_without_a_download(self, gate):
        def never(*a):
            raise AssertionError("should not download")

        update = gate({"copy_text": "Copy", "image_path": "c1/round-1.jpg", "image_version": 0}, never)
        assert "creative" not in update

    def test_an_unreadable_repaint_falls_back_to_the_original(self, gate):
        def broken(*a):
            raise RuntimeError("storage down")

        update = gate({"copy_text": "Copy", "image_path": "c1/round-1.jpg", "image_version": 2}, broken)
        assert "creative" not in update

    def test_edited_copy_and_repaint_combine(self, gate):
        update = gate({"copy_text": "Edited copy", "image_path": "c1/round-1.jpg", "image_version": 1})
        assert update["creative"].copy_text == "Edited copy" and update["creative"].image_bytes == b"repainted"
