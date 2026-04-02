test_deps:
	pip install .[test]

version: k8s_backup/version.py
k8s_backup/version.py: setup.py
	echo "__version__ = '$$(python setup.py --version)'" > $@

lint: test_deps
	flake8 k8s_backup/ test/

test: test_deps lint
	coverage run --source=k8s_backup -m pytest test/ -v

init_docs:
	cd docs; sphinx-quickstart

docs:
	$(MAKE) -C docs html

install: clean version
	pip install wheel
	python setup.py bdist_wheel
	pip install --upgrade dist/*.whl

clean:
	-rm -rf build dist
	-rm -rf *.egg-info

.PHONY: lint test test_deps docs install clean

include common.mk
