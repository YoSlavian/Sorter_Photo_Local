PYTHON ?= python3
NPM ?= npm
PACKAGE := src/bpmn_architect
FRONTEND := frontend
EXAMPLES := examples
IMAGES := docs/images

.PHONY: help install install-frontend build-frontend studio dev \
        test lint types check frontend-test frontend-lint frontend-types \
        check-all examples e2e clean

help:
	@echo "install           установить пакет с dev-зависимостями"
	@echo "install-frontend  установить зависимости фронтенда"
	@echo "build-frontend    собрать SPA в пакет Python"
	@echo "studio            запустить приложение (нужна сборка фронтенда)"
	@echo "dev               backend с автоперезагрузкой (фронтенд: cd frontend && npm run dev)"
	@echo ""
	@echo "test / lint / types / check      проверки Python"
	@echo "frontend-test / -lint / -types   проверки фронтенда"
	@echo "check-all                        всё сразу"
	@echo "e2e                              сквозной сценарий в браузере"
	@echo ""
	@echo "examples          пересобрать docs/images/*.svg"
	@echo "clean             удалить кеши и артефакты сборки"

install:
	$(PYTHON) -m pip install -e ".[dev,studio]"

install-frontend:
	cd $(FRONTEND) && $(NPM) install

build-frontend:
	cd $(FRONTEND) && $(NPM) run build

studio: build-frontend
	$(PYTHON) -m bpmn_architect studio

dev:
	$(PYTHON) -m bpmn_architect studio --reload --no-browser

# -- Python -------------------------------------------------------------------

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check $(PACKAGE) tests

types:
	$(PYTHON) -m mypy

check: lint types test

# -- frontend -----------------------------------------------------------------

frontend-test:
	cd $(FRONTEND) && $(NPM) test

frontend-lint:
	cd $(FRONTEND) && $(NPM) run lint

frontend-types:
	cd $(FRONTEND) && $(NPM) run typecheck

check-all: check frontend-lint frontend-types frontend-test build-frontend

# -- end to end ---------------------------------------------------------------

e2e:
	@echo "Требуется запущенный сервер: make studio (в отдельном терминале)"
	$(PYTHON) tests/e2e/studio.py

# -- assets -------------------------------------------------------------------

examples:
	@mkdir -p $(IMAGES)
	$(PYTHON) -m bpmn_architect build $(EXAMPLES)/order_request.ru.txt -o $(IMAGES)/order_request.svg -f svg -q
	$(PYTHON) -m bpmn_architect build $(EXAMPLES)/invoice_approval.dsl -o $(IMAGES)/invoice_approval.svg -f svg -q
	@echo "превью обновлены в $(IMAGES)"

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
	rm -rf $(PACKAGE)/server/static $(FRONTEND)/node_modules
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.egg-info' -type d -prune -exec rm -rf {} +
