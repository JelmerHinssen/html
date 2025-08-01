from typing import Any, Callable, Optional, TypeVar
import yaml
from dataclasses import dataclass, field

from visitor import visitor, Visitable


class DOMNode(Visitable, visitable=False):
    def to_html(self, indentation=""):
        raise NotImplementedError("to_html is abstract")

    def html_escape(self, text: str) -> str:
        return text

    def is_simple(self) -> bool:
        return True


@dataclass
class TextNode(DOMNode):
    text: str

    def to_html(self, indentation=""):
        return f"{indentation}{self.html_escape(self.text)}"


@dataclass
class HTMLTag(DOMNode):
    tag: str
    id: Optional[str] = None
    classes: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    children: list[DOMNode] = field(default_factory=list)

    def is_simple(self):
        if len(self.children) > 1:
            return False
        return all([child.is_simple() for child in self.children])

    def to_html(self, indentation=""):
        lines: list[str] = []

        attrs: dict[str, str] = {}
        if self.id:
            attrs["id"] = self.id
        if self.classes:
            attrs["class"] = " ".join(self.classes)
        attrs.update(**self.attributes)
        if attrs:
            attr_str = f" {" ".join([f"{key}=\"{value}\"" for key, value in attrs.items()])}"
        else:
            attr_str = ""
        lines.append(f"{indentation}<{self.tag}{attr_str}>")
        indent = "" if self.is_simple() else (indentation + "  ")
        for child in self.children:
            lines.append(child.to_html(indent))
        lines.append(f"{indent and indentation}</{self.tag}>")
        joiner = "" if self.is_simple() else "\n"
        return joiner.join(lines)


def generate_tag(key: str, value: dict | Any):
    return HTMLTag("div", classes=[key], children=generate_html(value))


def generate_html(obj: dict | list | Any) -> list[DOMNode]:
    if isinstance(obj, dict):
        return [generate_tag(key, value) for key, value in obj.items()]
    elif isinstance(obj, list):
        return [HTMLTag("div", children=generate_html(value)) for value in obj]
    else:
        return [TextNode(str(obj))]


@dataclass
class SimpleSelector:
    tag: Optional[str] = None
    id: Optional[str] = None
    classes: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = []
        if self.tag:
            parts.append(self.tag)
        if self.id:
            parts.append(f"@{self.id}")
        parts.extend(f".{cls}" for cls in self.classes)
        return "".join(parts) or "*"

    def matches(self, tag: HTMLTag):
        if self.tag and self.tag != tag.tag:
            return False
        if self.id and self.id != tag.id:
            return False
        for cls in self.classes:
            if cls not in tag.classes:
                return False
        return True


@dataclass
class DirectChildSelector:
    children: list[SimpleSelector]

    def __str__(self):
        return ">".join(map(str, self.children))

    def match_exactly(self, path: list[HTMLTag]):
        return len(path) == len(self.children) and all(
            [selector.matches(tag) for selector, tag in zip(self.children, path)]
        )

    def matches(self, path: list[HTMLTag]):
        return self.match_exactly(path[-len(self.children) :])


@dataclass
@visitor(DOMNode, "generate")
class HTMLSerializer:
    custom_generators: list[tuple[DirectChildSelector, Callable[[HTMLTag], str]]]

    def gen(self, node: DOMNode):
        return self.generate(node, "", [])

    def generate(self, node: DOMNode, indentation: str, path: list[HTMLTag]) -> str:
        return ""

    def generateTextNode(self, node: TextNode, indentation: str, path: list[HTMLTag]) -> str:
        return node.text

    def generateHTMLTag(self, node: HTMLTag, indentation: str, path: list[HTMLTag]) -> str:
        p = path + [node]
        for selector, generator in self.custom_generators:
            if selector.matches(p):
                return generator(node)

        lines: list[str] = []
        attrs: dict[str, str] = {}
        if node.id:
            attrs["id"] = node.id
        if node.classes:
            attrs["class"] = " ".join(node.classes)
        attrs.update(**node.attributes)
        if attrs:
            attr_str = f" {" ".join([f"{key}=\"{value}\"" for key, value in attrs.items()])}"
        else:
            attr_str = ""
        if node.children:
            lines.append(f"{indentation}<{node.tag}{attr_str}>")
            indent = "" if node.is_simple() else (indentation + "  ")
            for child in node.children:
                lines.append(self.generate(child, indent, p))
            lines.append(f"{indent and indentation}</{node.tag}>")
            joiner = "" if node.is_simple() else "\n"
            return joiner.join(lines)
        else:
            return f"{indentation}<{node.tag}{attr_str}/>"


@dataclass
class Node(Visitable, visitable=False):
    path: list[str] = field(default_factory=list, repr=False)


@dataclass
class DictNode(Node):
    children: dict[str, Node] = field(default_factory=dict)


@dataclass
class ListNode(Node):
    children: list[Node] = field(default_factory=list)


@dataclass
class ValueNode(Node):
    value: Any = None


_T = TypeVar("_T", bound=Node)


@dataclass
@visitor(Node, "generate")
class HTMLGenerator:
    custom_generators: list[tuple[list[str], Callable[[Node], list[DOMNode]]]]

    def generate(self, node: Node) -> list[DOMNode]:
        raise NotImplementedError()

    @staticmethod
    def path_matches(filter: list[str], path: list[str]) -> bool:
        if len(filter) == 0 and len(path) == 0:
            return True
        if len(path) == 0:
            return False
        if len(filter) == 0:
            return False
        if filter[0] == path[0] or filter[0] == "*":
            return HTMLGenerator.path_matches(filter[1:], path[1:])
        if filter[0] == "**":
            return HTMLGenerator.path_matches(filter[1:], path[1:]) or HTMLGenerator.path_matches(filter, path[1:])
        return False

    def custom_generator(self, node: Node) -> list[DOMNode] | None:
        for path, generator in self.custom_generators:
            if self.path_matches(path, node.path):
                return generator(node)
        return None

    @staticmethod
    def use_custom_generator(f: Callable[["HTMLGenerator", _T], list[DOMNode]]):
        def inner(self: "HTMLGenerator", node: _T) -> list[DOMNode]:
            custom = self.custom_generator(node)
            if custom is not None:
                return custom
            return f(self, node)

        return inner

    def generateNamedNode(self, name: str, node: Node) -> list[DOMNode]:
        custom = self.custom_generator(node)
        if custom is not None:
            return custom
        classes = [name] if name else []
        return [HTMLTag("div", classes=classes, children=self.generate(node))]

    def generateDictNode(self, node: DictNode) -> list[DOMNode]:
        tags = []
        for key, value in node.children.items():
            tags.extend(self.generateNamedNode(key, value))
        return tags

    @use_custom_generator
    def generateListNode(self, node: ListNode) -> list[DOMNode]:
        tags = []
        for child in node.children:
            tags.extend(self.generateNamedNode("", child))
        return tags

    @use_custom_generator
    def generateValueNode(self, node: ValueNode) -> list[DOMNode]:
        return [TextNode(str(node.value))]


def make_node(obj: dict | list | Any, path: list[str] = []) -> Node:
    if isinstance(obj, dict):
        return DictNode(path, {key: make_node(value, path + [key]) for key, value in obj.items()})
    elif isinstance(obj, list):
        return ListNode(path, [make_node(value, path + [str(i)]) for i, value in enumerate(obj)])
    else:
        return ValueNode(path, obj)


def generate_circle(node: Node) -> list[DOMNode]:

    return [
        HTMLTag("div", classes=["circle"], children=generate_tile_collection(node)),
    ]


def generate_tile_collection(node: Node) -> list[DOMNode]:
    assert isinstance(node, DictNode)
    children: list[DOMNode] = []
    for key, value in node.children.items():
        assert isinstance(value, ValueNode)
        assert isinstance(value.value, int)
        for _ in range(value.value):
            children.append(HTMLTag("div", classes=["tile", f"tile-{key}"], children=[TextNode(key)]))
    return children


def generate_center(node: Node) -> list[DOMNode]:
    assert isinstance(node, DictNode)
    return [HTMLTag("div", classes=["center"], children=generate_tile_collection(node))]


def generate_building_line(node: Node) -> list[DOMNode]:
    assert isinstance(node, DictNode)
    children = []
    length: int = node.children["length"].value
    count: int = node.children["count"].value
    color: str = node.children["tile"].value
    for _ in range(5 - length):
        children.append(HTMLTag("div", classes=["tile", "tile-spacer"]))
    for _ in range(length - count):
        children.append(HTMLTag("div", classes=["tile", "tile-empty"]))
    for _ in range(count):
        children.append(HTMLTag("div", classes=["tile", f"tile-{color}"]))

    return [HTMLTag("div", classes=["buildingline"], children=children)]


def generate_tile(node: Node) -> list[DOMNode]:
    assert isinstance(node, DictNode)
    color = node.children["tile"].value.lower()
    occupied = node.children["occupied"].value
    classes = ["tile", f"tile-{color}"]
    if not occupied:
        classes.append(f"tile-empty")
    return [HTMLTag("div", classes=classes)]


def generate_floor_line(node: Node) -> list[DOMNode]:
    assert isinstance(node, ListNode)
    tags = []
    for child in node.children:
        tags.append(HTMLTag("div", classes=["tile", f"tile-{child.value.lower()}"]))
    for _ in range(7 - len(node.children)):
        tags.append(HTMLTag("div", classes=["tile", f"tile-empty"]))

    return tags


if __name__ == "__main__":
    with open("input.yaml") as f:
        yaml.SafeLoader.add_constructor(
            "tag:yaml.org,2002:python/object:__main__.Azul", yaml.SafeLoader.construct_mapping
        )
        obj = yaml.safe_load(f)
    node = make_node(obj)
    generator = HTMLGenerator(
        [
            (["**", "circles", "*"], generate_circle),
            (["**", "center"], generate_center),
            (["**", "building_lines", "*"], generate_building_line),
            (["**", "floor_line", "tiles"], generate_floor_line),
            (["**", "board", "**", "tiles", "*"], generate_tile),
        ]
    )
    html = HTMLTag("div", "main", children=generator.generate(node))
    print(html.to_html())
    print(f'<link rel="stylesheet" href="azul.css">')
    # # html = generate_tag("main", obj)
    # # # print(html.to_html())
    # # selector = DirectChildSelector([SimpleSelector(classes=["circles"]), SimpleSelector("div")])
    # # # print(selector)
    # # # print(html.to_html())
    # # generator = HTMLSerializer([(selector, lambda tag: "Custom generator")])
    # # generated = generator.gen(html)
    # # print(generated)
    # # print("Hey")
    # obj = {"hoi": "hey", "nested": {"list": [1, 2, 3], "value": "name"}}
    # node = make_node(obj)
    # print(node)
    # generator = HTMLGenerator([(["**", "value"], lambda node: [TextNode("Custom generator")])])
    # html = HTMLTag("div", "main", children=generator.generate(node))

    # print(html.to_html())
