"""
k8s_backup: Command-line YAML processor - kubernetes YAML documents

k8s_backup filters YAML documents to remove extra metadata that would prevent
clean back up and restore.
"""

import os
import sys
import argparse
import json
import shutil
import subprocess
from collections import OrderedDict
from datetime import datetime, date, time
import yaml

try:
    from kubernetes import client, config
    HAS_KUBERNETES = True
except ImportError:
    HAS_KUBERNETES = False

DEFAULT_RESOURCE_TYPES = [
    "pods", "services", "deployments", "configmaps", "secrets",
    "statefulsets", "daemonsets", "ingresses", "replicasets",
    "jobs", "cronjobs", "persistentvolumeclaims",
]


def clean_resource(resource):
    del_metadata_keys = [
        "creationTimestamp",
        "selfLink",
        "uid",
        "resourceVersion",
        "generation",
    ]
    del_annotations_keys = [
        "kubectl.kubernetes.io/last-applied-configuration",
        "control-plane.alpha.kubernetes.io/leader",
        "deployment.kubernetes.io/revision",
        "cattle.io/creator",
        "field.cattle.io/creatorId",
    ]
    if "status" in resource:
        del resource["status"]

    if resource.get("metadata"):
        for key in del_metadata_keys:
            if key in resource["metadata"]:
                del resource["metadata"][key]

        if resource["metadata"].get("annotations"):
            for key in del_annotations_keys:
                if key in resource["metadata"]["annotations"]:
                    del resource["metadata"]["annotations"][key]

            if resource["metadata"]["annotations"] == {}:
                del resource["metadata"]["annotations"]

        if resource["metadata"].get("namespace") == '':
            del resource["metadata"]["namespace"]

        if resource["metadata"] == {}:
            del resource["metadata"]

    if resource.get("kind") == "Service" and resource.get("spec"):
        if resource["spec"].get("clusterIP") is not None:
            del resource["spec"]["clusterIP"]
        if resource["spec"] == {}:
            del resource["spec"]
    return resource


def write_resources_to_directory(resources, output_dir):
    """Write each resource to <output_dir>/<namespace>/<kind>/<name>.yaml"""
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for resource in resources:
        kind = resource.get("kind", "Unknown")
        metadata = resource.get("metadata", {})
        name = metadata.get("name", "unnamed")
        namespace = metadata.get("namespace", "cluster")
        resource_dir = os.path.join(output_dir, namespace, kind)
        os.makedirs(resource_dir, exist_ok=True)
        filepath = os.path.join(resource_dir, "{}.yaml".format(name))
        with open(filepath, "w") as f:
            yaml.dump(resource, f, Dumper=OrderedDumper,
                      allow_unicode=True, default_flow_style=False)
        written.append(filepath)
    return written


def archive_directory(output_dir):
    """Create a tar.gz archive of the output directory and remove it."""
    archive_path = shutil.make_archive(output_dir, "gztar", os.path.dirname(output_dir),
                                       os.path.basename(output_dir))
    shutil.rmtree(output_dir)
    return archive_path


def discover_api_resources(context=None):
    """Use kubectl to discover all available API resource types."""
    cmd = ["kubectl", "api-resources", "--verbs=list", "-o", "name"]
    if context:
        cmd.extend(["--context", context])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]


def fetch_kubectl_resources(resource_types, namespace=None, all_namespaces=False,
                            context=None, selector=None):
    """Use kubectl to fetch resources and return as list of dicts."""
    resources = []
    for rt in resource_types:
        cmd = ["kubectl", "get", rt, "-o", "yaml"]
        if context:
            cmd.extend(["--context", context])
        if all_namespaces:
            cmd.append("--all-namespaces")
        elif namespace:
            cmd.extend(["--namespace", namespace])
        if selector:
            cmd.extend(["-l", selector])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("Warning: failed to get {}: {}".format(rt, result.stderr.strip()),
                  file=sys.stderr)
            continue
        data = yaml.safe_load(result.stdout)
        if data and data.get("items"):
            resources.extend(data["items"])
    return resources


def fetch_crd_instances(namespace=None, all_namespaces=False, context=None, selector=None):
    """Fetch all custom resource definition instances."""
    cmd = ["kubectl", "get", "customresourcedefinitions", "-o", "name"]
    if context:
        cmd.extend(["--context", context])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    crd_names = [line.strip().split("/", 1)[-1]
                 for line in result.stdout.strip().split("\n") if line.strip()]
    if not crd_names:
        return []
    return fetch_kubectl_resources(crd_names, namespace=namespace,
                                   all_namespaces=all_namespaces, context=context,
                                   selector=selector)


def fetch_pod_logs(namespace=None, all_namespaces=False, context=None,
                   selector=None, output_dir="."):
    """Fetch logs for all pods and write to <output_dir>/logs/<ns>/<pod>/<container>.log"""
    cmd = ["kubectl", "get", "pods", "-o",
           "jsonpath={range .items[*]}{.metadata.namespace} {.metadata.name} "
           "{range .spec.containers[*]}{.name},{end}|{end}"]
    if context:
        cmd.extend(["--context", context])
    if all_namespaces:
        cmd.append("--all-namespaces")
    elif namespace:
        cmd.extend(["--namespace", namespace])
    if selector:
        cmd.extend(["-l", selector])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Warning: failed to list pods for logs: {}".format(result.stderr.strip()),
              file=sys.stderr)
        return []
    log_files = []
    entries = [e.strip() for e in result.stdout.split("|") if e.strip()]
    for entry in entries:
        parts = entry.split()
        if len(parts) < 3:
            continue
        ns, pod = parts[0], parts[1]
        containers = [c for c in parts[2].split(",") if c]
        for container in containers:
            log_dir = os.path.join(output_dir, "logs", ns, pod)
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "{}.log".format(container))
            log_cmd = ["kubectl", "logs", "--namespace", ns, pod, container]
            if context:
                log_cmd.extend(["--context", context])
            log_result = subprocess.run(log_cmd, capture_output=True, text=True)
            with open(log_file, "w") as f:
                f.write(log_result.stdout)
            log_files.append(log_file)
            print("  logs: {}/{}/{}".format(ns, pod, container), file=sys.stderr)
    return log_files


class Parser(argparse.ArgumentParser):
    def print_help(self):
        k8s_filter_help = argparse.ArgumentParser.format_help(self).splitlines()
        print("\n".join(["usage: k8s_filter [options] [YAML file...]"] + k8s_filter_help[1:] + [""]))


class OrderedLoader(yaml.SafeLoader):
    pass


class OrderedDumper(yaml.SafeDumper):
    pass


class JSONDateTimeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime, date, time)):
            return o.isoformat()
        return json.JSONEncoder.default(self, o)


def construct_mapping(loader, node):
    loader.flatten_mapping(node)
    return OrderedDict(loader.construct_pairs(node))


def represent_dict_order(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())


def parse_unknown_tags(loader, tag_suffix, node):
    if isinstance(node, yaml.nodes.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.nodes.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.nodes.MappingNode):
        return construct_mapping(loader, node)


OrderedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
OrderedLoader.add_multi_constructor('', parse_unknown_tags)
OrderedDumper.add_representer(OrderedDict, represent_dict_order)


RESOURCE_TYPE_MAP = {
    "pods": ("CoreV1Api", "list_namespaced_pod", "list_pod_for_all_namespaces"),
    "services": ("CoreV1Api", "list_namespaced_service", "list_service_for_all_namespaces"),
    "configmaps": ("CoreV1Api", "list_namespaced_config_map", "list_config_map_for_all_namespaces"),
    "secrets": ("CoreV1Api", "list_namespaced_secret", "list_secret_for_all_namespaces"),
    "persistentvolumeclaims": ("CoreV1Api", "list_namespaced_persistent_volume_claim",
                               "list_persistent_volume_claim_for_all_namespaces"),
    "deployments": ("AppsV1Api", "list_namespaced_deployment", "list_deployment_for_all_namespaces"),
    "statefulsets": ("AppsV1Api", "list_namespaced_stateful_set", "list_stateful_set_for_all_namespaces"),
    "daemonsets": ("AppsV1Api", "list_namespaced_daemon_set", "list_daemon_set_for_all_namespaces"),
    "replicasets": ("AppsV1Api", "list_namespaced_replica_set", "list_replica_set_for_all_namespaces"),
    "jobs": ("BatchV1Api", "list_namespaced_job", "list_job_for_all_namespaces"),
    "cronjobs": ("BatchV1Api", "list_namespaced_cron_job", "list_cron_job_for_all_namespaces"),
    "ingresses": ("NetworkingV1Api", "list_namespaced_ingress", "list_ingress_for_all_namespaces"),
}


def fetch_k8s_resources(args):
    """Fetch resources from a Kubernetes cluster and return as list of dicts."""
    if not HAS_KUBERNETES:
        raise RuntimeError(
            "kubernetes Python client is not installed. Install with: pip install kubernetes")

    config.load_kube_config(context=args.context)
    api_clients = {}
    resources = []

    for resource_type in args.resource_type:
        rt = resource_type.lower()
        if rt not in RESOURCE_TYPE_MAP:
            raise ValueError("Unknown resource type: {}. Supported: {}".format(
                rt, ", ".join(sorted(RESOURCE_TYPE_MAP.keys()))))

        api_class_name, namespaced_method, all_ns_method = RESOURCE_TYPE_MAP[rt]

        if api_class_name not in api_clients:
            api_clients[api_class_name] = getattr(client, api_class_name)()
        api = api_clients[api_class_name]

        if args.all_namespaces:
            result = getattr(api, all_ns_method)()
        else:
            namespace = args.namespace or "default"
            result = getattr(api, namespaced_method)(namespace)

        for item in result.items:
            resource_dict = client.ApiClient().sanitize_for_serialization(item)
            resources.append(
                OrderedDict(resource_dict) if isinstance(resource_dict, dict) else resource_dict)

    return resources


def output_resources(resources, args, stream=None):
    """Write resources to stream or output directory."""
    if args.output_directory:
        output_dir = os.path.expanduser(args.output_directory)
        written = write_resources_to_directory(resources, output_dir)
        for path in written:
            print("  wrote: {}".format(path), file=sys.stderr)

        if args.logs:
            fetch_pod_logs(
                namespace=args.namespace,
                all_namespaces=args.all_namespaces,
                context=args.context,
                selector=args.selector,
                output_dir=output_dir,
            )

        if args.archive:
            archive_path = archive_directory(output_dir)
            print("  archived: {}".format(archive_path), file=sys.stderr)
        return

    if stream is None:
        stream = sys.stdout
    if args.yaml_output:
        yaml.dump_all(resources, stream=stream, Dumper=OrderedDumper,
                      width=args.width, allow_unicode=True, default_flow_style=False)
    else:
        json.dump(resources, stream, cls=JSONDateTimeEncoder, indent=2, ensure_ascii=False)
        stream.write("\n")


def get_parser(program_name):
    yaml_output_help, width_help = argparse.SUPPRESS, argparse.SUPPRESS

    if program_name == "k8s_backup":
        current_language = "YAML"
        json_output_help = "Give JSON output back"
        yaml_output_help = "Transcode output back into YAML and emit it"
        width_help = "When using --yaml-output, specify string wrap width"
    else:
        raise Exception("Unknown program name")

    description = __doc__.replace("k8s_backup", program_name).replace("YAML", current_language)
    parser_args = dict(prog=program_name, description=description,
                       formatter_class=argparse.RawTextHelpFormatter,
                       allow_abbrev=False)
    parser = Parser(**parser_args)

    output_group = parser.add_argument_group("output options")
    output_group.add_argument("--yaml-output", "--yml-output", "-y", action="store_true",
                              default=True, help=yaml_output_help)
    output_group.add_argument("--json-output", "-j", action="store_false", dest="yaml_output",
                              help=json_output_help)
    output_group.add_argument("--width", "-w", type=int, help=width_help)
    output_group.add_argument("--output-directory", "-d",
                              help="Write each resource to <dir>/<namespace>/<kind>/<name>.yaml")
    output_group.add_argument("--archive", "-z", action="store_true",
                              help="Archive the output directory as tar.gz and remove it")

    k8s_group = parser.add_argument_group("kubernetes options")
    k8s_group.add_argument("--context", help="Kubernetes context to use")
    k8s_group.add_argument("--namespace", "-n",
                           help="Kubernetes namespace (default: 'default')")
    k8s_group.add_argument("--resource-type", "-r", action="append",
                           help="Resource type to fetch (repeatable). "
                                "e.g. pods, services, deployments")
    k8s_group.add_argument("--all-namespaces", "-A", action="store_true",
                           help="Fetch from all namespaces")
    k8s_group.add_argument("--all-resources", action="store_true",
                           help="Auto-discover and fetch all API resource types via kubectl")
    k8s_group.add_argument("--include-crds", action="store_true",
                           help="Also fetch custom resource definition instances")
    k8s_group.add_argument("--selector", "-l",
                           help="Label selector to filter resources (e.g. app=nginx)")
    k8s_group.add_argument("--logs", action="store_true",
                           help="Also fetch pod container logs (requires -d)")

    parser.add_argument("files", nargs="*", type=argparse.FileType())
    return parser


def main(args=None, input_format="yaml", program_name="k8s_backup"):
    parser = get_parser(program_name)
    args, _ = parser.parse_known_args(args=args)

    if args.logs and not args.output_directory:
        parser.error("--logs requires --output-directory (-d)")

    if args.archive and not args.output_directory:
        parser.error("--archive requires --output-directory (-d)")

    # Kubernetes cluster fetch mode
    if args.resource_type or args.all_resources:
        try:
            input_data = []

            if args.all_resources:
                resource_types = discover_api_resources(context=args.context)
                input_data.extend(fetch_kubectl_resources(
                    resource_types,
                    namespace=args.namespace,
                    all_namespaces=args.all_namespaces,
                    context=args.context,
                    selector=args.selector,
                ))
            elif args.resource_type:
                # Check if all types are in the Python client map
                unknown_types = [rt for rt in args.resource_type
                                 if rt.lower() not in RESOURCE_TYPE_MAP]
                if unknown_types or args.selector:
                    # Fall back to kubectl for unknown types or when selector is used
                    input_data.extend(fetch_kubectl_resources(
                        args.resource_type,
                        namespace=args.namespace,
                        all_namespaces=args.all_namespaces,
                        context=args.context,
                        selector=args.selector,
                    ))
                else:
                    input_data.extend(fetch_k8s_resources(args))

            if args.include_crds:
                input_data.extend(fetch_crd_instances(
                    namespace=args.namespace,
                    all_namespaces=args.all_namespaces,
                    context=args.context,
                    selector=args.selector,
                ))

            input_data = [clean_resource(doc) for doc in input_data]
            output_resources(input_data, args)
        except Exception as e:
            parser.exit("{}: Error running k8s_backup: {}: {}.".format(
                program_name, type(e).__name__, e))
        return

    # Stdin/file mode
    if sys.stdin.isatty() and not args.files:
        return parser.print_help()

    try:
        input_streams = args.files if args.files else [sys.stdin]
        input_data = []
        for input_stream in input_streams:
            if input_format == "yaml":
                input_data.extend(yaml.load_all(input_stream, Loader=OrderedLoader))
            else:
                raise Exception("Unknown input format")

        input_data = [clean_resource(doc) for doc in input_data]
        output_resources(input_data, args)

        for input_stream in input_streams:
            input_stream.close()
    except Exception as e:
        parser.exit("{}: Error running k8s_backup: {}: {}.".format(
            program_name, type(e).__name__, e))


if __name__ == "__main__":
    main()
