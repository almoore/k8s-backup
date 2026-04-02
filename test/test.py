#!/usr/bin/env python

import os
import sys
import io
import json
import shutil
import tempfile
import unittest
from collections import OrderedDict

from k8s_backup import (
    clean_resource, main, get_parser,
    write_resources_to_directory, archive_directory,
)


class TestCleanResource(unittest.TestCase):
    def test_removes_status(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "test"},
            "status": {"phase": "Running"},
        })
        result = clean_resource(resource)
        self.assertNotIn("status", result)

    def test_strips_metadata_fields(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": OrderedDict({
                "name": "test",
                "creationTimestamp": "2024-01-01T00:00:00Z",
                "selfLink": "/api/v1/pods/test",
                "uid": "abc-123",
                "resourceVersion": "12345",
                "generation": 1,
            }),
        })
        result = clean_resource(resource)
        self.assertEqual(result["metadata"], OrderedDict({"name": "test"}))

    def test_strips_annotations(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": OrderedDict({
                "name": "test",
                "annotations": OrderedDict({
                    "kubectl.kubernetes.io/last-applied-configuration": "{}",
                    "control-plane.alpha.kubernetes.io/leader": "true",
                    "deployment.kubernetes.io/revision": "1",
                    "cattle.io/creator": "admin",
                    "field.cattle.io/creatorId": "user-123",
                    "custom-annotation": "keep-me",
                }),
            }),
        })
        result = clean_resource(resource)
        self.assertEqual(
            result["metadata"]["annotations"],
            OrderedDict({"custom-annotation": "keep-me"}),
        )

    def test_removes_empty_annotations(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": OrderedDict({
                "name": "test",
                "annotations": OrderedDict({
                    "kubectl.kubernetes.io/last-applied-configuration": "{}",
                }),
            }),
        })
        result = clean_resource(resource)
        self.assertNotIn("annotations", result["metadata"])

    def test_removes_empty_namespace(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": OrderedDict({
                "name": "test",
                "namespace": "",
            }),
        })
        result = clean_resource(resource)
        self.assertNotIn("namespace", result["metadata"])

    def test_removes_empty_metadata(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": OrderedDict({
                "creationTimestamp": "2024-01-01T00:00:00Z",
                "uid": "abc-123",
            }),
        })
        result = clean_resource(resource)
        self.assertNotIn("metadata", result)

    def test_service_cluster_ip_removed(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": OrderedDict({"name": "my-svc"}),
            "spec": OrderedDict({
                "clusterIP": "10.0.0.1",
                "ports": [{"port": 80}],
            }),
        })
        result = clean_resource(resource)
        self.assertNotIn("clusterIP", result["spec"])
        self.assertIn("ports", result["spec"])

    def test_service_empty_spec_removed(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": OrderedDict({"name": "my-svc"}),
            "spec": OrderedDict({"clusterIP": "10.0.0.1"}),
        })
        result = clean_resource(resource)
        self.assertNotIn("spec", result)

    def test_missing_kind_no_error(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "metadata": OrderedDict({"name": "test"}),
        })
        result = clean_resource(resource)
        self.assertEqual(result["metadata"]["name"], "test")

    def test_no_metadata(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "ConfigMap",
        })
        result = clean_resource(resource)
        self.assertEqual(result["kind"], "ConfigMap")

    def test_returns_resource(self):
        resource = OrderedDict({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": OrderedDict({"name": "test"}),
        })
        result = clean_resource(resource)
        self.assertIs(result, resource)


class TestCLIOutput(unittest.TestCase):
    def run_k8s_backup(self, input_data, args=None, input_format="yaml"):
        if args is None:
            args = []
        stdin, stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = io.StringIO(input_data)
            sys.stdout = io.StringIO()
            main(args, input_format=input_format)
        except SystemExit:
            pass
        finally:
            result = sys.stdout.getvalue()
            sys.stdin, sys.stdout = stdin, stdout
        return result

    def test_yaml_default_output(self):
        input_data = ("apiVersion: v1\nkind: Pod\nmetadata:\n"
                      "  name: test\nstatus:\n  phase: Running\n")
        result = self.run_k8s_backup(input_data)
        self.assertIn("name: test", result)
        self.assertNotIn("status", result)
        self.assertNotIn("phase", result)

    def test_json_output(self):
        input_data = ("apiVersion: v1\nkind: ConfigMap\n"
                      "metadata:\n  name: test\n")
        result = self.run_k8s_backup(input_data, ["-j"])
        parsed = json.loads(result)
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["kind"], "ConfigMap")
        self.assertEqual(parsed[0]["metadata"]["name"], "test")

    def test_multi_document_yaml(self):
        input_data = ("---\napiVersion: v1\nkind: Pod\n"
                      "metadata:\n  name: pod1\n"
                      "---\napiVersion: v1\nkind: Pod\n"
                      "metadata:\n  name: pod2\n")
        result = self.run_k8s_backup(input_data)
        self.assertIn("pod1", result)
        self.assertIn("pod2", result)

    def test_width_option(self):
        input_data = ("apiVersion: v1\nkind: ConfigMap\n"
                      "metadata:\n  name: test\n"
                      "  labels:\n    long-key: long-value\n")
        result_narrow = self.run_k8s_backup(input_data, ["-w", "20"])
        result_wide = self.run_k8s_backup(input_data, ["-w", "200"])
        self.assertIsNotNone(result_narrow)
        self.assertIsNotNone(result_wide)

    def test_unknown_tags_handled(self):
        input_data = "x: !foo bar\n"
        result = self.run_k8s_backup(input_data)
        self.assertIn("x: bar", result)

    def test_empty_input(self):
        result = self.run_k8s_backup("{}")
        self.assertIsNotNone(result)

    def test_json_output_with_datetime(self):
        input_data = ("apiVersion: v1\nkind: Pod\nmetadata:\n"
                      "  name: test\n"
                      "  creationTimestamp: 2024-01-01T00:00:00Z\n")
        result = self.run_k8s_backup(input_data, ["-j"])
        parsed = json.loads(result)
        self.assertNotIn("creationTimestamp", parsed[0].get("metadata", {}))


class TestWriteResourcesToDirectory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_writes_single_resource(self):
        resources = [OrderedDict({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": OrderedDict({
                "name": "my-pod",
                "namespace": "default",
            }),
        })]
        written = write_resources_to_directory(resources, self.tmpdir)
        self.assertEqual(len(written), 1)
        expected = os.path.join(self.tmpdir, "default", "Pod", "my-pod.yaml")
        self.assertEqual(written[0], expected)
        self.assertTrue(os.path.exists(expected))

    def test_writes_multiple_namespaces(self):
        resources = [
            OrderedDict({
                "apiVersion": "v1", "kind": "ConfigMap",
                "metadata": OrderedDict({"name": "cm1", "namespace": "ns1"}),
            }),
            OrderedDict({
                "apiVersion": "v1", "kind": "ConfigMap",
                "metadata": OrderedDict({"name": "cm2", "namespace": "ns2"}),
            }),
        ]
        written = write_resources_to_directory(resources, self.tmpdir)
        self.assertEqual(len(written), 2)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmpdir, "ns1", "ConfigMap", "cm1.yaml")))
        self.assertTrue(os.path.exists(
            os.path.join(self.tmpdir, "ns2", "ConfigMap", "cm2.yaml")))

    def test_cluster_scoped_resource(self):
        resources = [OrderedDict({
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": OrderedDict({"name": "my-ns"}),
        })]
        written = write_resources_to_directory(resources, self.tmpdir)
        expected = os.path.join(self.tmpdir, "cluster", "Namespace", "my-ns.yaml")
        self.assertEqual(written[0], expected)
        self.assertTrue(os.path.exists(expected))

    def test_file_content_is_valid_yaml(self):
        resources = [OrderedDict({
            "apiVersion": "v1", "kind": "Pod",
            "metadata": OrderedDict({"name": "test", "namespace": "default"}),
        })]
        write_resources_to_directory(resources, self.tmpdir)
        filepath = os.path.join(self.tmpdir, "default", "Pod", "test.yaml")
        with open(filepath) as f:
            loaded = yaml.safe_load(f)
        self.assertEqual(loaded["kind"], "Pod")
        self.assertEqual(loaded["metadata"]["name"], "test")


class TestArchiveDirectory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.tmpdir, "backup")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_archive_and_removes_dir(self):
        os.makedirs(self.output_dir)
        with open(os.path.join(self.output_dir, "test.txt"), "w") as f:
            f.write("test content")
        archive_path = archive_directory(self.output_dir)
        self.assertTrue(os.path.exists(archive_path))
        self.assertFalse(os.path.exists(self.output_dir))
        self.assertTrue(archive_path.endswith(".tar.gz"))


class TestOutputDirectory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_k8s_backup_with_dir(self, input_data, extra_args=None):
        if extra_args is None:
            extra_args = []
        stdin, stdout, stderr = sys.stdin, sys.stdout, sys.stderr
        try:
            sys.stdin = io.StringIO(input_data)
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            main(["-d", self.tmpdir] + extra_args)
        except SystemExit:
            pass
        finally:
            out = sys.stdout.getvalue()
            err = sys.stderr.getvalue()
            sys.stdin, sys.stdout, sys.stderr = stdin, stdout, stderr
        return out, err

    def test_split_output_to_files(self):
        input_data = ("apiVersion: v1\nkind: Pod\nmetadata:\n"
                      "  name: my-pod\n  namespace: default\n")
        out, err = self.run_k8s_backup_with_dir(input_data)
        expected = os.path.join(self.tmpdir, "default", "Pod", "my-pod.yaml")
        self.assertTrue(os.path.exists(expected))
        # stdout should be empty when writing to directory
        self.assertEqual(out, "")

    def test_split_multi_document(self):
        input_data = ("---\napiVersion: v1\nkind: ConfigMap\n"
                      "metadata:\n  name: cm1\n  namespace: ns1\n"
                      "---\napiVersion: v1\nkind: Secret\n"
                      "metadata:\n  name: s1\n  namespace: ns2\n")
        self.run_k8s_backup_with_dir(input_data)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmpdir, "ns1", "ConfigMap", "cm1.yaml")))
        self.assertTrue(os.path.exists(
            os.path.join(self.tmpdir, "ns2", "Secret", "s1.yaml")))


class TestCLIParsing(unittest.TestCase):
    def test_parser_creation(self):
        parser = get_parser("k8s_backup")
        self.assertIsNotNone(parser)

    def test_yaml_output_default(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args([])
        self.assertTrue(args.yaml_output)

    def test_json_flag_disables_yaml(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["-j"])
        self.assertFalse(args.yaml_output)

    def test_width_arg(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["-w", "80"])
        self.assertEqual(args.width, 80)

    def test_context_arg(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["--context", "my-ctx"])
        self.assertEqual(args.context, "my-ctx")

    def test_namespace_arg(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["-n", "kube-system"])
        self.assertEqual(args.namespace, "kube-system")

    def test_resource_type_repeatable(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["-r", "pods", "-r", "services"])
        self.assertEqual(args.resource_type, ["pods", "services"])

    def test_all_namespaces_flag(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["-A"])
        self.assertTrue(args.all_namespaces)

    def test_output_directory_arg(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["-d", "/tmp/backup"])
        self.assertEqual(args.output_directory, "/tmp/backup")

    def test_archive_flag(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["-z", "-d", "/tmp/backup"])
        self.assertTrue(args.archive)

    def test_all_resources_flag(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["--all-resources"])
        self.assertTrue(args.all_resources)

    def test_include_crds_flag(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["--include-crds"])
        self.assertTrue(args.include_crds)

    def test_selector_arg(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["-l", "app=nginx"])
        self.assertEqual(args.selector, "app=nginx")

    def test_logs_flag(self):
        parser = get_parser("k8s_backup")
        args, _ = parser.parse_known_args(["--logs"])
        self.assertTrue(args.logs)

    def test_unknown_program_name_raises(self):
        with self.assertRaises(Exception):
            get_parser("unknown_program")


import yaml  # noqa: E402


if __name__ == '__main__':
    unittest.main()
