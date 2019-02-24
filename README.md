k8s_backup: Command-line YAML/JSON processor - backing up kubernetes config files
=================================================================================

Installation
------------

```bash
pip install k8s_backup
```

Before using ``k8s_backup``, you also have to install its dependency

Synopsis
--------

``k8s_backup`` takes can tak YAML input, converts it to JSON, and filters out the portions which are specific to the running instance:

    cat input.yml | k8s_backup

By default it will output YAML, ``--yaml-output``/``-y`` argument is to explicitly declar this.

    cat input.yml | k8s_backup

Use the ``--width``/``-w`` argument to pass the line wrap width for string literals. 

To output the config as JSON use, ``--json-output``/``-j``

YAML `tags <http://www.yaml.org/spec/1.2/spec.html#id2764295>`_ in the input are ignored (any nested data is treated as
untagged). Key order is preserved.

Because YAML treats JSON as a dialect of YAML, you can use k8s_backup to convert JSON to YAML: ``k8s_backup -y . < in.json > out.yml``.


Authors
-------
* Alex Moore

Links
-----
* [Project home page (GitHub)](https://github.com/almoore/k8s_backup)
* [Documentation (Read the Docs)](https://k8s_backup.readthedocs.io/en/latest/)
* [Package distribution (PyPI) ](https://pypi.python.org/pypi/k8s_backup)

Bugs
----
Please report bugs, issues, feature requests, etc. on [GitHub](https://github.com/almoore/k8s_backup/issues).

License
-------
Licensed under the terms of the [Apache License, Version 2.0](http://www.apache.org/licenses/LICENSE-2.0).

[![](https://img.shields.io/travis/almoore/k8s_backup.svg)](https://travis-ci.org/almoore/k8s_backup)
[![](https://codecov.io/github/almoore/k8s_backup/coverage.svg?branch=master)](https://codecov.io/github/almoore/k8s_backup?branch=master)
[![](https://img.shields.io/pypi/v/k8s_backup.svg)](https://pypi.python.org/pypi/k8s_backup)
[![](https://img.shields.io/pypi/l/k8s_backup.svg)](https://pypi.python.org/pypi/k8s_backup)
[![](https://readthedocs.org/projects/k8s_backup/badge/?version=latest)](https://k8s_backup.readthedocs.io/)
