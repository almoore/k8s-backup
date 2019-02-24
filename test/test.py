#!/usr/bin/env python
# coding: utf-8

from __future__ import absolute_import, division, print_function, unicode_literals

import os, sys, unittest, tempfile, json, io, platform, subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from k8s_backup import main  # noqa

USING_PYTHON2 = True if sys.version_info < (3, 0) else False
USING_PYPY = True if platform.python_implementation() == "PyPy" else False

yaml_with_tags = """
foo: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  3766343436323632623130303
xyz: !!mytag
  foo: bar
  baz: 1
xyzzt: !binary
  - 1
  - 2
  - 3
scalar-red: !color FF0000
scalar-orange: !color FFFF00
mapping-red: !color-mapping {r: 255, g: 0, b: 0}
mapping-orange:
  !color-mapping
  r: 255
  g: 255
  b: 0
"""

class Testk8s_backup(unittest.TestCase):
    def run_k8s_backup(self, input_data, args, expect_exit_codes={os.EX_OK}, input_format="yaml"):
        stdin, stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = io.StringIO(input_data)
            sys.stdout = io.BytesIO() if USING_PYTHON2 else io.StringIO()
            main(args, input_format=input_format)
        except SystemExit as e:
            self.assertIn(e.code, expect_exit_codes)
        finally:
            result = sys.stdout.getvalue()
            if USING_PYTHON2:
                result = result.decode("utf-8")
            sys.stdin, sys.stdout = stdin, stdout
        return result

    def test_k8s_backup(self):
        for input_format in "yaml", "JSON", "toml":
            try:
                main(["--help"], input_format=input_format)
            except SystemExit as e:
                self.assertEqual(e.code, 0)
        self.assertEqual(self.run_k8s_backup("{}", ["."]), "")
        self.assertEqual(self.run_k8s_backup("foo:\n bar: 1\n baz: {bat: 3}", [".foo.baz.bat"]), "")
        self.assertEqual(self.run_k8s_backup("[1, 2, 3]", ["--yaml-output", "-M", "."]), "- 1\n- 2\n- 3\n")
        self.assertEqual(self.run_k8s_backup("foo:\n bar: 1\n baz: {bat: 3}", ["-y", ".foo.baz.bat"]), "3\n...\n")
        self.assertEqual(self.run_k8s_backup("[aaaaaaaaaa bbb]", ["-y", "."]), "- aaaaaaaaaa bbb\n")
        self.assertEqual(self.run_k8s_backup("[aaaaaaaaaa bbb]", ["-y", "-w", "8", "."]), "- aaaaaaaaaa\n  bbb\n")
        self.assertEqual(self.run_k8s_backup('{"понедельник": 1}', ['.["понедельник"]']), "")
        self.assertEqual(self.run_k8s_backup('{"понедельник": 1}', ["-y", '.["понедельник"]']), "1\n...\n")
        self.assertEqual(self.run_k8s_backup("- понедельник\n- вторник\n", ["-y", "."]), "- понедельник\n- вторник\n")

    def test_k8s_backup_err(self):
        err = ('k8s_backup: Error running jq: ScannerError: while scanning for the next token\nfound character \'%\' that '
               'cannot start any token\n  in "<file>", line 1, column 3.')
        self.run_k8s_backup("- %", ["."], expect_exit_codes={err, 2})

    def test_k8s_backup_arg_passthrough(self):
        self.assertEqual(self.run_k8s_backup("{}", ["--arg", "foo", "bar", "--arg", "x", "y", "--indent", "4", "."]), "")
        self.assertEqual(self.run_k8s_backup("{}", ["--arg", "foo", "bar", "--arg", "x", "y", "-y", "--indent", "4", ".x=$x"]),
                         "x: y\n")
        err = "k8s_backup: Error running jq: {}Error: [Errno 32] Broken pipe{}".format("IO" if USING_PYTHON2 else "BrokenPipe",
                                                                               ": '<fdopen>'." if USING_PYPY else ".")
        self.run_k8s_backup("{}", ["--indent", "9", "."], expect_exit_codes={err, 2})

        with tempfile.NamedTemporaryFile() as tf, tempfile.TemporaryFile() as tf2:
            tf.write(b'.a')
            tf.seek(0)
            tf2.write(b'{"a": 1}')
            for arg in "--from-file", "-f":
                tf2.seek(0)
                self.assertEqual(self.run_k8s_backup("", ["-y", arg, tf.name, self.fd_path(tf2)]), '1\n...\n')

    @unittest.skipIf(subprocess.check_output(["jq", "--version"]) < b"jq-1.6", "Test options introduced in jq 1.6")
    def test_jq16_arg_passthrough(self):
        self.assertEqual(self.run_k8s_backup("{}", ["-y", ".a=$ARGS.positional", "--args", "a", "b"]), "a:\n- a\n- b\n")
        self.assertEqual(self.run_k8s_backup("{}", [".", "--jsonargs", "a", "b"]), "")

    def fd_path(self, fh):
        return "/dev/fd/{}".format(fh.fileno())

    def test_multidocs(self):
        self.assertEqual(self.run_k8s_backup("---\na: b\n---\nc: d", ["-y", "."]), "a: b\n---\nc: d\n")
        with tempfile.TemporaryFile() as tf, tempfile.TemporaryFile() as tf2:
            tf.write(b'{"a": "b"}')
            tf.seek(0)
            tf2.write(b'{"a": 1}')
            tf2.seek(0)
            self.assertEqual(self.run_k8s_backup("", ["-y", ".a", self.fd_path(tf), self.fd_path(tf2)]), 'b\n--- 1\n...\n')

    def test_datetimes(self):
        self.assertEqual(self.run_k8s_backup("- 2016-12-20T22:07:36Z\n", ["."]), "")
        self.assertEqual(self.run_k8s_backup("- 2016-12-20T22:07:36Z\n", ["-y", "."]), "- '2016-12-20T22:07:36'\n")

        self.assertEqual(self.run_k8s_backup("2016-12-20", ["."]), "")
        self.assertEqual(self.run_k8s_backup("2016-12-20", ["-y", "."]), "'2016-12-20'\n")

    def test_unrecognized_tags(self):
        self.assertEqual(self.run_k8s_backup("!!foo bar\n", ["."]), "")
        self.assertEqual(self.run_k8s_backup("!!foo bar\n", ["-y", "."]), "bar\n...\n")
        self.assertEqual(self.run_k8s_backup("x: !foo bar\n", ["-y", "."]), "x: bar\n")
        self.assertEqual(self.run_k8s_backup("x: !!foo bar\n", ["-y", "."]), "x: bar\n")
        with tempfile.TemporaryFile() as tf:
            tf.write(yaml_with_tags.encode())
            tf.seek(0)
            self.assertEqual(self.run_k8s_backup("", ["-y", ".xyz.foo", self.fd_path(tf)]), 'bar\n...\n')

    @unittest.expectedFailure
    def test_times(self):
        """
        Timestamps are parsed as sexagesimals in YAML 1.1 but not 1.2. No PyYAML support for YAML 1.2 yet. See issue 10
        """
        self.assertEqual(self.run_k8s_backup("11:12:13", ["."]), "")
        self.assertEqual(self.run_k8s_backup("11:12:13", ["-y", "."]), "'11:12:13'\n")

    def test_xq(self):
        self.assertEqual(self.run_k8s_backup("<foo/>", ["."], input_format="JSON"), "")
        self.assertEqual(self.run_k8s_backup("<foo/>", ["-x", ".foo.x=1"], input_format="JSON"),
                         '<foo>\n  <x>1</x>\n</foo>\n')
        with tempfile.TemporaryFile() as tf, tempfile.TemporaryFile() as tf2:
            tf.write(b'<a><b/></a>')
            tf.seek(0)
            tf2.write(b'<a><c/></a>')
            tf2.seek(0)
            self.assertEqual(self.run_k8s_backup("", ["-x", ".a", self.fd_path(tf), self.fd_path(tf2)], input_format="JSON"),
                             '<b></b>\n<c></c>\n')
        err = ("k8s_backup: Error converting JSON to JSON: cannot represent non-object types at top level. "
               "Use --JSON-root=name to envelope your output with a root element.")
        self.run_k8s_backup("[1]", ["-x", "."], expect_exit_codes=[err])

    def test_xq_dtd(self):
        with tempfile.TemporaryFile() as tf:
            tf.write(b'<a><b c="d">e</b><b>f</b></a>')
            tf.seek(0)
            self.assertEqual(self.run_k8s_backup("", ["-x", ".a", self.fd_path(tf)], input_format="JSON"),
                             '<b c="d">e</b><b>f</b>\n')
            tf.seek(0)
            self.assertEqual(self.run_k8s_backup("", ["-x", "--JSON-dtd", ".", self.fd_path(tf)], input_format="JSON"),
                             '<?JSON version="1.0" encoding="utf-8"?>\n<a>\n  <b c="d">e</b>\n  <b>f</b>\n</a>\n')
            tf.seek(0)
            self.assertEqual(
                self.run_k8s_backup("", ["-x", "--JSON-dtd", "--JSON-root=g", ".a", self.fd_path(tf)], input_format="JSON"),
                '<?JSON version="1.0" encoding="utf-8"?>\n<g>\n  <b c="d">e</b>\n  <b>f</b>\n</g>\n'
            )

    def test_tq(self):
        self.assertEqual(self.run_k8s_backup("", ["."], input_format="toml"), "")
        self.assertEqual(self.run_k8s_backup("", ["-t", ".foo.x=1"], input_format="toml"),
                         '[foo]\nx = 1\n')

        self.assertEqual(self.run_k8s_backup("[input]\n"
                                     "test_val = 1234\n",
                                     ["-t", ".input"], input_format="toml"),
                         "test_val = 1234\n")

        err = "k8s_backup: Error converting JSON to TOML: cannot represent non-object types at top level."
        self.run_k8s_backup('[1]', ["-t", "."], expect_exit_codes=[err])

    @unittest.skipIf(sys.version_info < (3, 5),
                     "argparse option abbreviation interferes with opt passthrough, can't be disabled until Python 3.5")
    def test_abbrev_opt_collisions(self):
        with tempfile.TemporaryFile() as tf, tempfile.TemporaryFile() as tf2:
            self.assertEqual(
                self.run_k8s_backup("", ["-y", "-e", "--slurp", ".[0] == .[1]", "-", self.fd_path(tf), self.fd_path(tf2)]),
                "true\n...\n"
            )


if __name__ == '__main__':
    unittest.main()
