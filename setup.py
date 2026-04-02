#!/usr/bin/env python

from setuptools import setup, find_packages

tests_require = ["coverage", "flake8", "wheel"]
docs_require = ["sphinx", "m2r", "recommonmark"]

setup(
    name="k8s-backup",
    version="0.1.0",
    url="https://github.com/almoore/k8s_backup",
    license="Apache Software License",
    author="Alex Moore",
    author_email="alexander.g.moore1@gmail.com",
    description="Command-line Kubernetes YAML/JSON processor - for backing up YAML/JSON documents of kubernetes config",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.8",
    install_requires=[
        "setuptools",
        "PyYAML >= 3.11",
    ],
    extras_require={
        "test": tests_require,
        "docs": docs_require,
        "kubernetes": ["kubernetes"],
    },
    tests_require=tests_require,
    packages=find_packages(exclude=["test"]),
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'k8s-backup=k8s_backup:main',
        ],
    },
    test_suite="test",
    classifiers=[
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules"
    ]
)
