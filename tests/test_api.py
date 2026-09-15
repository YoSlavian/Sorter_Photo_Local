"""The HTTP API contract."""

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="Studio extra is not installed")

from fastapi.testclient import TestClient  # noqa: E402

from bpmn_architect.server.app import create_app  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
DESCRIPTION = (EXAMPLES / "order_request.ru.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def diagram(client: TestClient) -> dict:
    response = client.post("/api/build", json={"text": DESCRIPTION})
    assert response.status_code == 200
    return response.json()


class TestStatus:
    def test_health(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_info_lists_capabilities(self, client):
        info = client.get("/api/info").json()
        assert set(info["modes"]) == {"deterministic", "ai", "hybrid"}
        assert set(info["providers"]) == {"anthropic", "openai", "local"}
        assert any(item["type"] == "exclusiveGateway" for item in info["elementTypes"])

    def test_openapi_document_is_complete(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for expected in (
            "/api/build",
            "/api/parse",
            "/api/validate",
            "/api/layout",
            "/api/clarify",
            "/api/describe",
            "/api/bpmn/import",
            "/api/bpmn/export",
            "/api/project/export",
            "/api/project/import",
        ):
            assert expected in paths


class TestBuild:
    def test_returns_a_complete_diagram(self, diagram):
        assert diagram["bpmn"].startswith("<?xml")
        assert len(diagram["elements"]) == diagram["meta"]["elementCount"]
        assert diagram["validation"]["ok"] is True
        assert diagram["meta"]["mode"] == "deterministic"
        assert diagram["meta"]["deterministic"] is True

    def test_elements_carry_what_the_editor_needs(self, diagram):
        element = next(e for e in diagram["elements"] if e["type"] == "userTask")
        assert set(element) >= {
            "id", "type", "name", "category", "lane", "laneName",
            "documentation", "incoming", "outgoing",
        }
        assert element["laneName"]

    def test_source_map_links_elements_to_the_text(self, diagram):
        assert diagram["sourceMap"]
        entry = next(iter(diagram["sourceMap"].values()))
        assert set(entry) == {"elementId", "sentence", "line", "start", "end", "exact"}
        assert DESCRIPTION[entry["start"] : entry["end"]] == entry["sentence"]

    def test_explanation_and_narrative_are_present(self, diagram):
        assert "<xor>" in diagram["explanation"]
        assert "Процесс" in diagram["narrative"]

    def test_options_are_honoured(self, client):
        response = client.post(
            "/api/build",
            json={
                "text": DESCRIPTION,
                "options": {"useLanes": False, "processId": "Custom", "executable": True},
            },
        )
        payload = response.json()
        assert payload["lanes"] == []
        assert payload["meta"]["processId"] == "Custom"
        assert 'isExecutable="true"' in payload["bpmn"]

    def test_empty_text_is_rejected(self, client):
        assert client.post("/api/build", json={"text": "   "}).status_code == 400

    def test_unknown_mode_is_rejected_by_the_schema(self, client):
        response = client.post(
            "/api/build", json={"text": "任意", "options": {"mode": "telepathy"}}
        )
        assert response.status_code == 422

    def test_ai_mode_without_a_provider_reports_clearly(self, client):
        response = client.post(
            "/api/build", json={"text": DESCRIPTION, "options": {"mode": "ai"}}
        )
        assert response.status_code == 422
        assert "not configured" in response.json()["detail"]

    def test_hybrid_mode_falls_back_to_deterministic(self, client):
        response = client.post(
            "/api/build", json={"text": DESCRIPTION, "options": {"mode": "hybrid"}}
        )
        assert response.status_code == 200
        assert response.json()["meta"]["deterministic"] is True


class TestParse:
    def test_explains_without_building(self, client):
        payload = client.post("/api/parse", json={"text": DESCRIPTION}).json()
        assert "process:" in payload["explanation"]
        assert payload["language"] == "ru"
        assert payload["deterministic"] is True


class TestDiagramOperations:
    def test_validate(self, client, diagram):
        payload = client.post("/api/validate", json={"bpmn": diagram["bpmn"]}).json()
        assert payload["ok"] is True
        assert set(payload["counts"]) == {"error", "warning", "info"}

    def test_layout_returns_geometry(self, client, diagram):
        payload = client.post("/api/layout", json={"bpmn": diagram["bpmn"]}).json()
        assert payload["meta"]["relaidOut"] is True
        assert len(payload["elements"]) == len(diagram["elements"])

    def test_import_round_trip(self, client, diagram):
        payload = client.post(
            "/api/bpmn/import",
            json={"bpmn": diagram["bpmn"], "sourceText": DESCRIPTION},
        ).json()
        assert [e["id"] for e in payload["elements"]] == [
            e["id"] for e in diagram["elements"]
        ]
        assert payload["meta"]["layoutWasGenerated"] is False
        assert payload["sourceMap"]

    def test_describe(self, client, diagram):
        text = client.post("/api/describe", json={"bpmn": diagram["bpmn"]}).json()["text"]
        assert "Процесс начинается" in text

    def test_describe_in_english(self, client, diagram):
        text = client.post(
            "/api/describe", json={"bpmn": diagram["bpmn"], "language": "en"}
        ).json()["text"]
        assert "The process starts" in text

    def test_malformed_bpmn_is_a_client_error(self, client):
        assert client.post("/api/validate", json={"bpmn": "<broken"}).status_code == 400


class TestClarify:
    def test_answers_are_applied_to_the_model(self, client):
        vague = (
            "Процесс начинается с заявки.\n"
            "Менеджер проверяет заявку.\n"
            "Далее выполняется обработка.\n"
            "Процесс завершается."
        )
        built = client.post("/api/build", json={"text": vague}).json()
        question = next(q for q in built["clarifications"] if q["kind"] == "naming")

        answered = client.post(
            "/api/clarify",
            json={"bpmn": built["bpmn"], "answers": {question["id"]: "Обработать обращение"}},
        ).json()
        names = [element["name"] for element in answered["elements"]]
        assert "Обработать обращение" in names
        assert not any(q["kind"] == "naming" for q in answered["clarifications"])


class TestExports:
    def test_bpmn_download(self, client, diagram):
        response = client.post("/api/bpmn/export", json={"bpmn": diagram["bpmn"]})
        assert response.headers["content-type"].startswith("application/xml")
        assert "attachment" in response.headers["content-disposition"]

    def test_svg_download(self, client, diagram):
        response = client.post("/api/export/svg", json={"bpmn": diagram["bpmn"]})
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.text.startswith("<svg")

    def test_json_download(self, client, diagram):
        response = client.post("/api/export/json", json={"bpmn": diagram["bpmn"]})
        assert set(response.json()) == {"process", "lanes", "nodes", "flows", "layout"}


class TestProjects:
    def test_save_and_reopen(self, client, diagram):
        saved = client.post(
            "/api/project/export",
            json={
                "bpmn": diagram["bpmn"],
                "sourceText": DESCRIPTION,
                "name": "Обработка заявки",
                "settings": {"zoom": 1.25, "theme": "dark"},
            },
        ).json()
        assert saved["filename"].endswith(".bpmn-project")

        restored = client.post("/api/project/import", json={"project": saved["project"]}).json()
        assert restored["sourceText"] == DESCRIPTION
        assert restored["settings"] == {"zoom": 1.25, "theme": "dark"}
        assert restored["metadata"]["name"] == "Обработка заявки"
        assert len(restored["diagram"]["elements"]) == len(diagram["elements"])

    def test_corrupt_project_is_reported(self, client):
        assert client.post("/api/project/import", json={"project": "{"}).status_code == 400

    def test_a_newer_project_version_is_refused_with_advice(self, client):
        response = client.post(
            "/api/project/import",
            json={"project": '{"version": 99, "bpmn": "<x/>"}'},
        )
        assert response.status_code == 400
        assert "newer than this build" in response.json()["detail"]

    def test_project_without_a_diagram_is_reported(self, client):
        assert (
            client.post(
                "/api/project/import", json={"project": '{"version": 1, "bpmn": ""}'}
            ).status_code
            == 400
        )


class TestRobustness:
    @pytest.mark.parametrize(
        "name", sorted(p.name for p in EXAMPLES.iterdir() if p.is_file())
    )
    def test_every_example_builds_through_the_api(self, client, name):
        text = (EXAMPLES / name).read_text(encoding="utf-8")
        payload = client.post("/api/build", json={"text": text}).json()
        assert payload["validation"]["ok"] is True
        assert payload["bpmn"].count("<bpmndi:BPMNShape") >= len(payload["elements"])

    @pytest.mark.parametrize(
        "text", ["Одно предложение", "???", "Процесс завершается.", "a" * 5000]
    )
    def test_degenerate_input_never_returns_a_server_error(self, client, text):
        assert client.post("/api/build", json={"text": text}).status_code < 500
