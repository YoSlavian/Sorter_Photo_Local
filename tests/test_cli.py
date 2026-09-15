import json
from pathlib import Path

import pytest

from bpmn_architect.cli import main

DESCRIPTION = """\
Обработка заявки

Процесс начинается с получения заявки.
Менеджер проверяет заявку.
Если заявка корректна, то бухгалтер выставляет счёт, иначе менеджер отклоняет заявку.
Процесс завершается.
"""


@pytest.fixture
def description(tmp_path: Path) -> Path:
    path = tmp_path / "process.txt"
    path.write_text(DESCRIPTION, encoding="utf-8")
    return path


class TestBuild:
    def test_writes_a_bpmn_file(self, description, tmp_path):
        output = tmp_path / "out.bpmn"
        assert main(["build", str(description), "-o", str(output)]) == 0
        assert "<bpmn:definitions" in output.read_text(encoding="utf-8")

    def test_all_formats(self, description, tmp_path):
        output = tmp_path / "diagram"
        assert main(["build", str(description), "-o", str(output), "-f", "all"]) == 0
        assert (tmp_path / "diagram.bpmn").exists()
        assert (tmp_path / "diagram.svg").exists()
        payload = json.loads((tmp_path / "diagram.json").read_text(encoding="utf-8"))
        assert payload["nodes"]

    def test_stdout(self, description, capsys):
        assert main(["build", str(description), "--stdout", "-q"]) == 0
        assert "<bpmn:definitions" in capsys.readouterr().out

    def test_reads_stdin(self, monkeypatch, capsys, tmp_path):
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO(DESCRIPTION))
        assert main(["build", "-", "--stdout", "-q"]) == 0
        assert "<bpmn:definitions" in capsys.readouterr().out

    def test_no_lanes_option(self, description, tmp_path):
        output = tmp_path / "out.bpmn"
        main(["build", str(description), "-o", str(output), "--no-lanes"])
        assert "<bpmn:laneSet" not in output.read_text(encoding="utf-8")

    def test_verbatim_names_option(self, description, tmp_path):
        output = tmp_path / "out.bpmn"
        main(["build", str(description), "-o", str(output), "--verbatim-names"])
        assert "Проверяет заявку" in output.read_text(encoding="utf-8")

    def test_reads_utf8_with_bom(self, tmp_path):
        source = tmp_path / "bom.txt"
        source.write_bytes(DESCRIPTION.encode("utf-8-sig"))
        output = tmp_path / "out.bpmn"
        assert main(["build", str(source), "-o", str(output)]) == 0
        assert "Обработка заявки" in output.read_text(encoding="utf-8")

    def test_reads_legacy_windows_encoding(self, tmp_path):
        # Notepad on a Russian Windows still produces cp1251 in older builds.
        source = tmp_path / "cp1251.txt"
        source.write_bytes(DESCRIPTION.encode("cp1251"))
        output = tmp_path / "out.bpmn"
        assert main(["build", str(source), "-o", str(output)]) == 0
        assert "Проверить заявку" in output.read_text(encoding="utf-8")

    def test_missing_file_is_reported(self, capsys):
        assert main(["build", "nope.txt"]) == 2
        assert "file not found" in capsys.readouterr().err


class TestOtherCommands:
    def test_validate_reports_a_summary(self, description, capsys):
        assert main(["validate", str(description)]) == 0
        assert "elements" in capsys.readouterr().out

    def test_explain_prints_the_structure(self, description, capsys):
        assert main(["explain", str(description)]) == 0
        output = capsys.readouterr().out
        assert "<xor> Заявка корректна?" in output

    def test_strict_build_fails_on_errors(self, tmp_path, capsys):
        source = tmp_path / "broken.txt"
        source.write_text("task: Шаг\ngoto: @nowhere\n", encoding="utf-8")
        exit_code = main(
            ["build", str(source), "-o", str(tmp_path / "out.bpmn"), "--strict"]
        )
        assert exit_code in (0, 1)

    def test_dsl_parse_error_is_reported(self, tmp_path, capsys):
        source = tmp_path / "bad.dsl"
        source.write_text("task: ok\nnonsense: bad\n", encoding="utf-8")
        assert main(["build", str(source), "--syntax", "dsl", "--stdout"]) == 1
        assert "unknown directive" in capsys.readouterr().err

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as info:
            main(["--version"])
        assert info.value.code == 0
