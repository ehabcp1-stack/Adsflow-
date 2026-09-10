"""Critical API endpoints — the full V1 journey through HTTP."""
from __future__ import annotations

import time

API = "/api/v1"


def test_health_and_root(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/").json()["by"] == "TADAFQ"


def test_dev_login_and_me(client):
    token = client.post(f"{API}/auth/dev-login").json()
    assert token["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token['access_token']}"}).json()
    assert me["email"] == "demo@tadafq.com"


def test_meta_options_expose_product_vocabulary(client):
    options = client.get(f"{API}/meta/options").json()
    assert options["durations"] == [15, 30, 45, 60]
    assert {o["value"] for o in options["goals"]} == {"leads", "sales", "awareness", "offer", "launch"}
    assert any(o["value"] == "auto_smart" for o in options["production_modes"])
    assert all(o["label_ar"] for o in options["languages"])


def test_providers_endpoint_reports_mock_mode(client):
    data = client.get(f"{API}/meta/providers").json()
    assert data["force_mock"] is True
    assert any(p["is_mock"] and p["active"] for p in data["providers"])


def test_full_journey_end_to_end(client):
    project = client.post(
        f"{API}/projects",
        json={
            "name": "مجمع الياسمين",
            "category": "real_estate",
            "goal": "leads",
            "platform": "instagram_reels",
            "duration_sec": 15,
            "language": "iraqi_arabic",
            "dialect": "iraqi_emotional",
            "tone": "emotional",
            "target_audience": "عوائل",
            "key_information": "شقق ١٥٠ متر\nأقساط ٤ سنوات",
            "cta": "احجز موعد زيارة",
        },
    ).json()
    pid = project["id"]
    assert project["state"] == "DRAFT"

    # Stage gate: concepts before analysis approval must fail.
    blocked = client.post(f"{API}/projects/{pid}/concepts/generate")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "approval_required"

    analysis = client.post(f"{API}/projects/{pid}/analysis/run").json()
    assert analysis["analysis"]["readiness_score"] >= 0
    assert analysis["analysis"]["director_notes"]
    assert analysis["state"] == "ANALYSIS_READY"
    assert client.post(f"{API}/projects/{pid}/analysis/approve").json()["ok"]

    concepts = client.post(f"{API}/projects/{pid}/concepts/generate").json()
    assert len(concepts["items"]) == 3
    concept_id = concepts["items"][0]["id"]
    refined = client.post(f"{API}/projects/{pid}/concepts/{concept_id}/refine", json={"action": "more_iraqi"}).json()
    assert refined["hook"]
    assert client.post(f"{API}/projects/{pid}/concepts/approve", json={"entity_id": concept_id}).json()["ok"]

    script = client.post(f"{API}/projects/{pid}/script/generate").json()
    assert len(script["variants"]) == 3
    selected = next(v for v in script["variants"] if v["variant"] == "primary")
    assert selected["voice_over_text"]
    assert client.post(f"{API}/projects/{pid}/script/approve", json={"entity_id": selected["id"]}).json()["ok"]

    voice = client.get(f"{API}/projects/{pid}/voice").json()
    assert len(voice["profiles"]) >= 3
    profile_id = voice["profiles"][0]["id"]
    preview = client.post(f"{API}/projects/{pid}/voice/preview", json={"voice_profile_id": profile_id}).json()
    assert preview["ok"] and preview["duration_sec"] > 0
    assert client.post(
        f"{API}/projects/{pid}/voice/select", json={"voice_profile_id": profile_id, "lock": True}
    ).json()["voice_locked"]

    storyboard = client.post(f"{API}/projects/{pid}/storyboard/generate").json()["storyboard"]
    assert storyboard["scenes"]
    assert storyboard["production_plan"]["scene_count"] == len(storyboard["scenes"])
    assert all(scene["thumbnail_url"] for scene in storyboard["scenes"])
    assert all(scene["compiled_prompt"] for scene in storyboard["scenes"])

    scene_id = storyboard["scenes"][0]["id"]
    client.post(f"{API}/projects/{pid}/scenes/{scene_id}/lock", json={"locked": True})
    locked = client.patch(f"{API}/projects/{pid}/scenes/{scene_id}", json={"changes": {"lighting": "x"}})
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "scene_locked"
    client.post(f"{API}/projects/{pid}/scenes/{scene_id}/lock", json={"locked": False})

    assert client.post(f"{API}/projects/{pid}/storyboard/approve").json()["ok"]
    assert client.post(f"{API}/projects/{pid}/production/approve").json()["state"] == "PRODUCTION_READY"

    started = client.post(f"{API}/projects/{pid}/production/start").json()
    assert started["jobs_created"] > 0
    for _ in range(60):
        status = client.get(f"{API}/projects/{pid}/production/status").json()
        if status["all_done"]:
            break
        time.sleep(0.5)
    assert status["jobs_failed"] == 0
    assert status["all_done"]
    client.post(f"{API}/projects/{pid}/production/finish")

    edit = client.post(
        f"{API}/projects/{pid}/edit/settings",
        json={"changes": {"editing_style": "fast_social", "captions_enabled": True}},
    ).json()
    assert edit["editing_style"] == "fast_social"
    render = client.post(f"{API}/projects/{pid}/edit/render").json()
    caption_track = next(t for t in render["timeline"] if t["type"] == "captions")
    assert caption_track["clips"] and caption_track["clips"][0]["direction"] == "rtl"

    qc = client.post(f"{API}/projects/{pid}/qc/run").json()
    assert 0 < qc["total_score"] <= 100
    assert qc["verdict"] in ("approved", "review", "fix_required")
    assert set(qc["weights"].values()) == {25, 20, 15, 20, 10, 10}
    client.post(f"{API}/projects/{pid}/qc/approve")

    export = client.post(f"{API}/projects/{pid}/export", json={"variant": "master"}).json()
    assert export["filename"].endswith(".mp4")
    assert export["width"] == 1080 and export["height"] == 1920

    final = client.get(f"{API}/projects/{pid}").json()
    assert final["state"] == "EXPORTED"

    archive = client.get(f"{API}/projects/{pid}/archive").json()
    assert archive["approved_script"] and archive["concepts"] and archive["exports"]

    costs = client.get(f"{API}/projects/{pid}/costs").json()
    assert costs["budget_limit_usd"] > 0
    assert isinstance(costs["ledger"], list) and costs["ledger"]

    duplicate = client.post(f"{API}/projects/{pid}/duplicate").json()
    assert duplicate["state"] == "DRAFT" and duplicate["id"] != pid


def test_qc_blocks_export_when_fix_required(client, db, make_project):
    from app.models import QCReport

    project = make_project(name="فحص", cta="")
    pid = project.id
    client.post(f"{API}/projects/{pid}/analysis/run")
    client.post(f"{API}/projects/{pid}/analysis/approve")
    client.post(f"{API}/projects/{pid}/concepts/generate")
    concepts = client.get(f"{API}/projects/{pid}/concepts").json()
    client.post(f"{API}/projects/{pid}/concepts/approve", json={"entity_id": concepts["items"][0]["id"]})
    client.post(f"{API}/projects/{pid}/script/generate")
    scripts = client.get(f"{API}/projects/{pid}/script").json()
    client.post(f"{API}/projects/{pid}/script/approve", json={"entity_id": scripts["variants"][0]["id"]})
    client.post(f"{API}/projects/{pid}/storyboard/generate")
    client.post(f"{API}/projects/{pid}/storyboard/approve")
    client.post(f"{API}/projects/{pid}/production/approve")
    client.post(f"{API}/projects/{pid}/edit/render")

    report = client.post(f"{API}/projects/{pid}/qc/run").json()
    db.expire_all()
    stored = db.query(QCReport).filter(QCReport.project_id == pid).order_by(QCReport.version.desc()).first()
    stored.ready_to_export = False
    stored.verdict = "fix_required"
    db.commit()

    blocked = client.post(f"{API}/projects/{pid}/export", json={"variant": "master"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "qc_failed"

    forced = client.post(f"{API}/projects/{pid}/export", json={"variant": "master", "force": True})
    assert forced.status_code == 200
    assert report["thresholds"]["approve"] == 90.0


def test_budget_guard_blocks_expensive_production(client, make_project):
    project = make_project(name="ميزانية صغيرة", budget_limit_usd=0.01)
    pid = project.id
    client.post(f"{API}/projects/{pid}/analysis/run")
    client.post(f"{API}/projects/{pid}/analysis/approve")
    client.post(f"{API}/projects/{pid}/concepts/generate")
    concepts = client.get(f"{API}/projects/{pid}/concepts").json()
    client.post(f"{API}/projects/{pid}/concepts/approve", json={"entity_id": concepts["items"][0]["id"]})
    client.post(f"{API}/projects/{pid}/script/generate")
    scripts = client.get(f"{API}/projects/{pid}/script").json()
    client.post(f"{API}/projects/{pid}/script/approve", json={"entity_id": scripts["variants"][0]["id"]})
    client.post(f"{API}/projects/{pid}/storyboard/generate")
    client.post(f"{API}/projects/{pid}/storyboard/approve")

    response = client.post(f"{API}/projects/{pid}/production/approve")
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "budget_exceeded"

    raised = client.post(f"{API}/projects/{pid}/budget", json={"budget_limit_usd": 25.0}).json()
    assert raised["budget_limit_usd"] == 25.0
    assert client.post(f"{API}/projects/{pid}/production/approve").status_code == 200


def test_asset_upload_and_analysis(client):
    files = [("files", ("hero.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"))]
    uploaded = client.post(f"{API}/assets/upload", files=files, data={"kind": "image"}).json()
    asset = uploaded["items"][0]
    assert asset["url"] and asset["analysis"]["quality_score"] > 0
    listed = client.get(f"{API}/assets").json()
    assert any(a["id"] == asset["id"] for a in listed["items"])


def test_brand_kit_crud(client):
    created = client.post(
        f"{API}/brands",
        json={"name": "Ward Group", "name_ar": "مجموعة الورد", "phone": "07701112233", "primary_color": "#0F172A"},
    ).json()
    assert created["id"]
    updated = client.patch(
        f"{API}/brands/{created['id']}",
        json={"name": "Ward Group", "name_ar": "مجموعة الورد", "phone": "07709998877", "editing_style": "luxury_clean"},
    ).json()
    assert updated["phone"] == "07709998877"
    assert client.delete(f"{API}/brands/{created['id']}").json()["ok"]


def test_unknown_project_returns_friendly_error(client):
    response = client.get(f"{API}/projects/does-not-exist")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "not_found" and body["message_ar"]
