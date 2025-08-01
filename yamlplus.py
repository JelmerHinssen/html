import yaml
import dataclasses as dc
import typeguard
import typing
import types
import enum

_T = typing.TypeVar("_T")


def yaml_tag(cls):

    if "yaml_tag" in cls.__dict__:
        return getattr(cls, "yaml_tag")
    return f"tag:yaml.org,2002:python/object:{cls.__module__}.{cls.__name__}"


def yaml_object(
    cls=None,
    /,
    *,
    loaders=[yaml.Loader, yaml.FullLoader, yaml.UnsafeLoader],
    dumper=yaml.Dumper,
    flow_style=None,
):
    def wrap(cls: _T) -> _T:
        yaml_loaders = getattr(cls, "yaml_loader", loaders)
        if not isinstance(yaml_loaders, list):
            yaml_loaders = [yaml_loaders]
        yaml_dumper = getattr(cls, "yaml_dumper", dumper)
        tag = yaml_tag(cls)
        cls.yaml_tag = tag
        yaml_flow_style = getattr(cls, "yaml_flow_style", flow_style)

        if issubclass(cls, enum.Enum):
            old_ignore = dumper.ignore_aliases
            dumper.ignore_aliases = lambda self, data: isinstance(data, cls) or old_ignore(self, data)

        def default_to_yaml(tag: str, dumper: yaml.Dumper, data: cls):
            if issubclass(cls, enum.Enum):
                result = dumper.represent_scalar(tag, data.name, style=yaml_flow_style)
                return result
            else:
                return dumper.represent_yaml_object(tag, data, cls, flow_style=yaml_flow_style)

        to_yaml = getattr(cls, "to_yaml", default_to_yaml)

        def default_from_yaml(loader: yaml.Loader, node):
            if issubclass(cls, enum.Enum):
                return cls[node.value]
            else:
                return loader.construct_yaml_object(node, cls)

        from_yaml = getattr(cls, "from_yaml", default_from_yaml)
        add_resolvers = getattr(cls, "yaml_resolvers", lambda *args: ...)

        for loader in yaml_loaders:
            loader.add_constructor(tag, from_yaml)
            add_resolvers(loader)

        yaml_dumper.add_representer(cls, lambda *args, **kwargs: to_yaml(tag, *args, **kwargs))
        add_resolvers(yaml_dumper)
        return cls

    if cls is not None:
        return wrap(cls)
    return wrap


def safe_yaml(*args, **kwargs):
    kwargs["loaders"] = [
        yaml.Loader,
        yaml.FullLoader,
        yaml.SafeLoader,
        yaml.UnsafeLoader,
    ]
    return yaml_object(*args, **kwargs)


@typing.dataclass_transform()
def dataclass(cls=None, /, *args, exclude_default=False, **kwargs):
    def wrap(cls: _T) -> _T:
        cls = dc.dataclass(cls, *args, **kwargs)
        paths = []
        tag = yaml_tag(cls)
        for field in dc.fields(cls):
            t = field.type
            if isinstance(t, str):
                continue
            origin = typing.get_origin(t)
            type_args = typing.get_args(t)
            if origin is None:
                if hasattr(t, "yaml_tag"):
                    paths.append((t.yaml_tag, [(tag, field.name)]))
            else:
                if origin is list:
                    (arg,) = type_args
                elif origin is dict:
                    (_, arg) = type_args
                else:
                    continue
                if isinstance(arg, type) and hasattr(arg, "yaml_tag"):
                    paths.append((arg.yaml_tag, [(tag, field.name), None]))

        old_yaml_resolvers = getattr(cls, "yaml_resolvers", lambda *args: ...)

        yaml_flow_style = getattr(cls, "yaml_flow_style", None)

        if exclude_default:

            def default_dc_to_yaml(tag: str, dumper: yaml.Dumper, data: cls):
                mapping: dict = data.__dict__.copy()
                for field_name in cls.__dataclass_fields__:
                    field: dc.Field = cls.__dataclass_fields__[field_name]
                    if field.default is not dc.MISSING and field.default == mapping.get(field.name, dc.MISSING):
                        mapping.pop(field.name, None)
                    elif field.default_factory is not dc.MISSING and field.default_factory() == mapping.get(
                        field.name, dc.MISSING
                    ):
                        mapping.pop(field.name, None)
                result = dumper.represent_mapping(tag, mapping, flow_style=yaml_flow_style)
                return result

            cls.to_yaml = default_dc_to_yaml

            def default_dc_from_yaml(loader: yaml.Loader, node):
                return loader.construct_yaml_object(node, cls)

            cls.from_yaml = default_dc_from_yaml

        @classmethod
        def yaml_resolvers(cls: type, resolver: yaml.resolver.BaseResolver):
            for t, p in paths:
                resolver.add_relative_path_resolver(t, p)
            old_yaml_resolvers(resolver)

        cls.yaml_resolvers = yaml_resolvers

        result = safe_yaml(cls)
        delattr(cls, "yaml_resolvers")
        if exclude_default:
            delattr(cls, "to_yaml")
            delattr(cls, "from_yaml")
        return result

    if cls is None:
        return wrap
    return wrap(cls)


old_descend_resolver = yaml.resolver.BaseResolver.descend_resolver


def descend_resolver(self: yaml.resolver.BaseResolver, current_node, current_index):
    if not self.yaml_path_resolvers:
        return
    exact_paths = {}
    prefix_paths = []
    if current_node:
        # depth = len(self.resolver_prefix_paths)
        for path, kind, depth in self.resolver_prefix_paths[-1]:
            if self.check_resolver_prefix(depth, path, kind, current_node, current_index):
                if len(path) > depth:
                    prefix_paths.append((path, kind, depth + 1))
                else:
                    exact_paths[kind] = self.yaml_path_resolvers[path, kind]
        if hasattr(self, "relative_path_resolvers"):
            for path, kind in self.relative_path_resolvers:
                prefix_paths.append((path, kind, 1))
    else:
        for path, kind in self.yaml_path_resolvers:
            if not path:
                exact_paths[kind] = self.yaml_path_resolvers[path, kind]
            else:
                prefix_paths.append((path, kind, 1))
    self.resolver_exact_paths.append(exact_paths)
    self.resolver_prefix_paths.append(prefix_paths)


@classmethod
def add_relative_path_resolver(cls: type[yaml.resolver.BaseResolver], tag, path, kind=None):
    from yaml.resolver import ResolverError
    from yaml.nodes import ScalarNode, SequenceNode, MappingNode

    if not "relative_path_resolvers" in cls.__dict__:
        cls.relative_path_resolvers = {}
    if not "yaml_path_resolvers" in cls.__dict__:
        cls.yaml_path_resolvers = cls.yaml_path_resolvers.copy()
    new_path = []
    for element in path:
        if isinstance(element, (list, tuple)):
            if len(element) == 2:
                node_check, index_check = element
            elif len(element) == 1:
                node_check = element[0]
                index_check = True
            else:
                raise ResolverError("Invalid path element: %s" % element)
        else:
            node_check = None
            index_check = element
        if node_check is str:
            node_check = ScalarNode
        elif node_check is list:
            node_check = SequenceNode
        elif node_check is dict:
            node_check = MappingNode
        elif (
            node_check not in [ScalarNode, SequenceNode, MappingNode]
            and not isinstance(node_check, str)
            and node_check is not None
        ):
            raise ResolverError("Invalid node checker: %s" % node_check)
        if not isinstance(index_check, (str, int)) and index_check is not None:
            raise ResolverError("Invalid index checker: %s" % index_check)
        new_path.append((node_check, index_check))
    if kind is str:
        kind = ScalarNode
    elif kind is list:
        kind = SequenceNode
    elif kind is dict:
        kind = MappingNode
    elif kind not in [ScalarNode, SequenceNode, MappingNode] and kind is not None:
        raise ResolverError("Invalid node kind: %s" % kind)
    cls.yaml_path_resolvers[tuple(new_path), kind] = tag
    cls.relative_path_resolvers[tuple(new_path), kind] = tag


yaml.resolver.BaseResolver.descend_resolver = descend_resolver
yaml.resolver.BaseResolver.add_relative_path_resolver = add_relative_path_resolver


# yaml.add_relative_path_resolver
def yaml_add_relative_path_resolver(tag, path, kind=None, Loader=None, Dumper=yaml.Dumper):
    """
    Add a path based resolver for the given tag.
    A path is a list of keys that forms a path
    to a node in the representation tree.
    Keys can be string values, integers, or None.
    """
    if Loader is None:
        yaml.loader.Loader.add_relative_path_resolver(tag, path, kind)
        yaml.loader.FullLoader.add_relative_path_resolver(tag, path, kind)
        yaml.loader.UnsafeLoader.add_relative_path_resolver(tag, path, kind)
    else:
        Loader.add_relative_path_resolver(tag, path, kind)
    Dumper.add_relative_path_resolver(tag, path, kind)


yaml.add_relative_path_resolver = yaml_add_relative_path_resolver
