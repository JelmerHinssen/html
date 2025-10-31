from enum import Enum
from typing import Any, Callable, Optional, TypeVar
import yaml
from dataclasses import dataclass, field, is_dataclass, asdict

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


@dataclass
class HTMLGenerator:
    generators: dict[type, Callable[[Any, "HTMLGenerator"], HTMLTag | list[DOMNode]]] = field(default_factory=dict)

    @staticmethod
    def collapse(items: list[list[DOMNode] | HTMLTag]) -> list[DOMNode]:
        result: list[DOMNode] = []
        for item in items:
            if isinstance(item, list):
                result.extend(item)
            else:
                result.append(item)
        return result

    @staticmethod
    def merge(parent: HTMLTag, child: HTMLTag | list[DOMNode]) -> HTMLTag:
        if isinstance(child, HTMLTag):
            parent.attributes.update(child.attributes)
            parent.classes.extend(child.classes)
            parent.id = child.id if child.id else parent.id
            parent.children.extend(child.children)
        else:
            parent.children.extend(child)
        return parent

    def generate_tag(self, key: str, value: Any) -> HTMLTag:
        return HTMLGenerator.merge(
            HTMLTag("div", classes=[key]),
            self.generate(value),
        )

    def __post_init__(self):
        self.generators[dict] = lambda x, gen: HTMLGenerator.collapse(
            [gen.generate_tag(key, value) for key, value in x.items()]
        )
        self.generators[list] = lambda x, gen: HTMLGenerator.collapse([gen(item) for item in x])
        self.generators[str] = lambda x, gen: [TextNode(x)]
        self.generators[int] = lambda x, gen: [TextNode(str(x))]
        self.generators[float] = lambda x, gen: [TextNode(str(x))]
        self.generators[bool] = lambda x, gen: [TextNode(str(x))]
        self.generators[type(None)] = lambda x, gen: [TextNode(str(x))]
        self.generators[Enum] = lambda x, gen: [TextNode(x.name)]

    def generate_from_dataclass(self, obj: Any) -> HTMLTag | list[DOMNode]:
        if not is_dataclass(obj):
            raise ValueError("Object is not a dataclass")
        no_html = getattr(obj, "_no_html_", []) + ["_no_html_"]
        fields = {
            field.name: getattr(obj, field.name)
            for field in obj.__dataclass_fields__.values()
            if field.name not in no_html
        }
        return self.generators[dict](fields, self)

    def generate(self, obj: Any) -> HTMLTag | list[DOMNode]:
        generator = self.generators.get(type(obj))
        if not generator:
            for cls in self.generators:
                if isinstance(obj, cls):
                    generator = self.generators[cls]
                    break
        if generator:
            return generator(obj, self)
        elif hasattr(obj, "to_html"):
            return obj.to_html(self)
        elif is_dataclass(obj):
            return self.generate_from_dataclass(obj)
        else:
            raise ValueError(f"No generator found for type {type(obj)}")

    def __call__(self, obj: Any) -> HTMLTag:
        node = self.generate(obj)
        if isinstance(node, list):
            return HTMLTag("div", children=node)
        return node


@dataclass
class Example:
    val1: str
    val2: int
    children: list[Any] = field(default_factory=list)

    def to_html(self, generator: HTMLGenerator) -> HTMLTag:
        tag: HTMLTag = generator(asdict(self))
        tag.classes.append("Example")
        return tag


if __name__ == "__main__":
    data = {
        "title": "My Document",
        "options": {
            "option1": True,
            "option2": "Some value",
            "option3": 42,
        },
        "example": Example(val1="Hello", val2=123, children=["Child 1", "Child 2"]),
        "content": [
            {"type": "paragraph", "text": "This is a paragraph."},
            {"type": "image", "src": "image.png", "alt": "An image"},
        ],
    }

    generator = HTMLGenerator()
    html = generator(data)
    print(html.to_html())
