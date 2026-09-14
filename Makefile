PYTHON ?= python3
PACKAGE := src/bpmn_architect
EXAMPLES := examples
IMAGES := docs/images

.PHONY: help install test lint types check examples clean

help:
	@echo "install   install the package with development dependencies"
	@echo "test      run the test suite"
	@echo "lint      run ruff"
	@echo "types     run mypy in strict mode"
	@echo "check     lint + types + test"
	@echo "examples  regenerate docs/images/*.svg from examples/"
	@echo "clean     remove caches and build artefacts"

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check $(PACKAGE) tests

types:
	$(PYTHON) -m mypy

check: lint types test

examples:
	@mkdir -p $(IMAGES)
	$(PYTHON) -m bpmn_architect build $(EXAMPLES)/order_request.ru.txt -o $(IMAGES)/order_request.svg -f svg -q
	$(PYTHON) -m bpmn_architect build $(EXAMPLES)/invoice_approval.dsl -o $(IMAGES)/invoice_approval.svg -f svg -q
	@echo "regenerated previews in $(IMAGES)"

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.egg-info' -type d -prune -exec rm -rf {} +
