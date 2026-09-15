#!/usr/bin/env python3
"""End-to-end check of BPMN Architect Studio in a real browser.

Deliberately not a pytest module: it needs a running server and a real
Chromium, so its place is a separate CI stage, not the suite a developer runs
every minute.

    pip install playwright && playwright install chromium
    bpmn-architect studio --no-browser &
    python tests/e2e/studio.py [--url http://localhost:8000] [--headed]

Exit code is 0 only when every check passed and the browser console stayed
clean; screenshots land next to the script unless --out says otherwise.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

DESCRIPTION = """\
Обработка заявки клиента

Процесс начинается с поступления заявки от клиента.
Менеджер проверяет заявку.
Если заявка заполнена правильно, менеджер передает её в бухгалтерию.
Бухгалтер формирует счет.
После оплаты система автоматически создает заказ.
Если заявка заполнена неправильно, менеджер возвращает её клиенту на доработку.
Процесс завершается после создания заказа."""


class Report:
    """Collects results so one failure does not hide the rest."""

    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []

    def check(self, name: str, condition: bool, detail: object = "") -> None:
        note = f"  [{detail}]" if detail else ""
        (self.passed if condition else self.failed).append(name)
        print(("  OK   " if condition else "  FAIL ") + name + note, flush=True)

    @property
    def ok(self) -> bool:
        return not self.failed


def labels_on_canvas(page: Page) -> str:
    """All rendered diagram text, whitespace removed, for robust matching."""
    texts = page.evaluate(
        "Array.from(document.querySelectorAll('.djs-container text'))"
        ".map(node => node.textContent || '')"
    )
    return "".join(texts).replace(" ", "")


def run(url: str, out: Path, headed: bool) -> Report:
    report = Report()
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        launch: dict[str, object] = {"headless": not headed}
        # Honour a pre-installed browser rather than downloading one.
        executable = os.getenv("CHROMIUM_PATH")
        if executable:
            launch["executable_path"] = executable
            launch["args"] = ["--no-sandbox"]
        browser = playwright.chromium.launch(**launch)  # type: ignore[arg-type]
        page = browser.new_page(viewport={"width": 1600, "height": 950})

        console_errors: list[str] = []
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        page.goto(url, wait_until="networkidle")
        report.check("страница загрузилась", page.title() == "BPMN Architect Studio")
        report.check("тулбар отрисован", page.locator(".ba-toolbar__title").is_visible())

        # -- text -> diagram --------------------------------------------------
        page.fill("textarea[aria-label='Описание процесса']", DESCRIPTION)
        page.click("button:has-text('Создать BPMN')")
        page.wait_for_selector(".djs-container .djs-element", timeout=20000)
        shapes = page.locator(".djs-container .djs-shape").count()
        report.check("диаграмма построена", shapes >= 7, f"{shapes} фигур")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(out / "studio-light.png"))

        # -- derived panels ---------------------------------------------------
        page.click("button[role='tab']:has-text('Элементы')")
        report.check(
            "список элементов", page.locator(".ba-list__item").count() >= 7
        )
        page.click("button[role='tab']:has-text('Проверка')")
        report.check(
            "проверка структуры",
            "корректна" in page.locator(".ba-summary .ba-pill").first.inner_text(),
        )
        page.click("button[role='tab']:has-text('Разбор')")
        page.wait_for_timeout(300)
        report.check("разбор текста показан", "process:" in page.locator(".ba-pre").first.inner_text())

        # -- selection and editing -------------------------------------------
        page.click("button[role='tab']:has-text('Свойства')")
        page.locator(".djs-element[data-element-id^='Activity_']").first.click()
        page.wait_for_timeout(500)
        report.check("свойства элемента", bool(page.input_value("#prop-name")))

        page.fill("#prop-name", "Проверить заявку клиента")
        page.press("#prop-name", "Enter")
        page.wait_for_timeout(800)
        report.check(
            "переименование применилось",
            "Проверитьзаявкуклиента" in labels_on_canvas(page),
        )

        page.click("button[title^='Отменить']")
        page.wait_for_timeout(600)
        report.check("undo откатил правку", "Проверитьзаявкуклиента" not in labels_on_canvas(page))

        page.click("button:has-text('Авто-компоновка')")
        page.wait_for_timeout(2000)
        report.check("авто-компоновка", page.locator(".djs-container .djs-shape").count() >= 7)

        # -- chrome -----------------------------------------------------------
        report.check(
            "встроенная палитра bpmn-js скрыта",
            not page.locator(".djs-palette").first.is_visible()
            if page.locator(".djs-palette").count()
            else True,
        )
        report.check("водяной знак bpmn.io виден", page.locator(".bjs-powered-by").is_visible())

        page.click("button[title^='Светлая']")
        page.wait_for_timeout(400)
        report.check("тёмная тема", page.evaluate("document.documentElement.dataset.theme") == "dark")
        page.screenshot(path=str(out / "studio-dark.png"))
        page.click("button[title^='Светлая']")

        page.click("button.ba-btn--sm:has-text('Элементы')")
        page.wait_for_timeout(300)
        report.check("палитра элементов", page.locator(".ba-palette__item").count() >= 15)
        page.click("button.ba-btn--sm:has-text('Текст')")

        page.keyboard.press("Control+k")
        page.wait_for_timeout(300)
        report.check("палитра команд", page.locator(".ba-command__item").count() > 5)
        page.keyboard.press("Escape")

        # -- exports ----------------------------------------------------------
        page.click("button:has-text('Экспорт')")
        with page.expect_download(timeout=15000) as download:
            page.click(".ba-command__item:has-text('BPMN')")
        content = Path(download.value.path()).read_text(encoding="utf-8")
        report.check(
            "экспорт BPMN",
            content.startswith("<?xml") and "bpmndi:BPMNDiagram" in content,
            f"{len(content)} байт",
        )

        page.click("button:has-text('Экспорт')")
        with page.expect_download(timeout=20000) as download:
            page.click(".ba-command__item:has-text('PNG')")
        png = Path(download.value.path()).read_bytes()
        report.check("экспорт PNG", png[:8] == b"\x89PNG\r\n\x1a\n", f"{len(png)} байт")

        with page.expect_download(timeout=15000) as download:
            page.click("button:has-text('Сохранить')")
        project = Path(download.value.path()).read_text(encoding="utf-8")
        report.check(
            "сохранение проекта", '"sourceText"' in project and '"bpmn"' in project
        )

        report.check("нет ошибок в консоли", not console_errors, "; ".join(console_errors[:2]))
        browser.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "screenshots")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    report = run(args.url, args.out, args.headed)
    print(f"\nИТОГО: {len(report.passed)} OK, {len(report.failed)} FAIL")
    for name in report.failed:
        print("  -", name)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
