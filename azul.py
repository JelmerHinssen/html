from dataclasses import asdict, field
import random
import threading
import time
from typing import Optional
from enum import Enum
import yaml

from tohtml import HTMLGenerator, DOMNode, HTMLTag, TextNode
from yamlplus import dataclass, yaml_object


@dataclass
class TileCollection:
    blue: int = 0
    cyan: int = 0
    red: int = 0
    yellow: int = 0
    black: int = 0

    def random_tile(self) -> "Tile":
        tiles = list(Tile)
        count = sum((getattr(self, tile.name.lower()) for tile in tiles))
        if count == 0:
            raise ValueError(f"Cannot draw from empty collection")
        rnd = random.randint(0, count - 1)
        for tile in tiles:
            if rnd < getattr(self, tile.name.lower()):
                return tile
            rnd -= getattr(self, tile.name.lower())
        raise ValueError(f"Invalid rng")

    def take_random_tile(self):
        tile = self.random_tile()
        self.remove_tile(tile)
        return tile

    def remove_tile(self, tile: "Tile"):
        old = getattr(self, tile.name.lower())
        if old <= 0:
            raise ValueError(f"Collection does not have {tile}")
        setattr(self, tile.name.lower(), old - 1)

    def add_tile(self, tile: "Tile"):
        setattr(self, tile.name.lower(), getattr(self, tile.name.lower()) + 1)

    def to_html(self, generator: HTMLGenerator) -> list["DOMNode"]:
        children = []
        for tile in Tile:
            count = getattr(self, tile.name.lower())
            for _ in range(count):
                children.append(
                    HTMLTag(
                        "div",
                        classes=["tile", f"tile-{tile.name.lower()}"],
                        children=[TextNode(tile.name.lower())],
                    )
                )
        return children


@dataclass
class CenterTileCollection(TileCollection):
    first: bool = True

    def to_html(self, generator: HTMLGenerator) -> list["DOMNode"]:
        children = super().to_html(generator)
        if self.first:
            children.insert(0, HTMLTag("div", classes=["tile", "tile-first"], children=[TextNode("first")]))
        return children


@dataclass
class Supply:
    available: TileCollection
    discarded: TileCollection
    center: CenterTileCollection
    circles: list[TileCollection]

    def to_html(self, generator: HTMLGenerator) -> list["DOMNode"]:
        children = []
        children.append(
            generator.merge(HTMLTag("div", classes=["available"]), generator.generate(asdict(self.available)))
        )
        children.append(
            generator.merge(HTMLTag("div", classes=["discarded"]), generator.generate(asdict(self.discarded)))
        )
        children.append(HTMLTag("div", classes=["center"], children=self.center.to_html(generator)))
        circles = HTMLTag("div", classes=["circles"])
        for circle in self.circles:
            circles.children.append(HTMLTag("div", classes=["circle"], children=circle.to_html(generator)))
        children.append(circles)
        return children


@yaml_object
class Tile(Enum):
    BLUE = 0
    CYAN = 1
    RED = 2
    YELLOW = 3
    BLACK = 4


class FirstTile(Enum):
    FIRST = -1


@dataclass
class BuildingLine:
    length: int
    tile: Optional[Tile] = None
    count: int = 0

    def to_html(self, generator: HTMLGenerator) -> HTMLTag:
        children = []
        for _ in range(5 - self.length):
            children.append(HTMLTag("div", classes=["tile", "tile-spacer"]))
        for _ in range(self.length - self.count):
            children.append(HTMLTag("div", classes=["tile", "tile-empty"]))
        if self.tile:
            for _ in range(self.count):
                children.append(HTMLTag("div", classes=["tile", f"tile-{self.tile.name.lower()}"]))
        return HTMLTag("div", classes=["buildingline"], children=children)


@dataclass
class FloorLine:
    tiles: list[Tile]

    def to_html(self, generator: HTMLGenerator) -> HTMLTag:
        children = []
        for tile in self.tiles:
            children.append(HTMLTag("div", classes=["tile", f"tile-{tile.name.lower()}"]))
        for _ in range(7 - len(self.tiles)):
            children.append(HTMLTag("div", classes=["tile", "tile-empty"]))
        return HTMLTag("div", children=children)


@dataclass
class TileSpot:
    tile: Tile
    occupied: bool = False

    def to_html(self, generator: HTMLGenerator) -> HTMLTag:
        classes = ["tile", f"tile-{self.tile.name.lower()}"]
        if not self.occupied:
            classes.append("tile-empty")
        return HTMLTag("div", classes=classes)


@dataclass
class BoardLine:
    tiles: list[TileSpot]


@dataclass
class Board:
    @staticmethod
    def empty_row(index):
        return BoardLine([TileSpot(Tile((i + index) % 5)) for i in range(5)])

    rows: list[BoardLine] = field(default_factory=lambda: [Board.empty_row(i) for i in range(5)])


@dataclass
class Player:
    building_lines: list[BuildingLine]
    floor_line: FloorLine
    board: Board


@dataclass
class Azul:
    supply: Supply
    players: list[Player]


azul: Azul | None = None
thread: threading.Thread | None = None


def get_state():
    if not azul:
        return "<h2>uh oh</h2>"
    generator = HTMLGenerator()
    html = generator(azul)
    html.id = "main"
    return html.to_html() + f"\n"


def run():
    global azul
    assert azul is not None
    time.sleep(1)
    supply = azul.supply.available
    azul.players[0].floor_line.tiles.append(supply.take_random_tile())


def start():
    global thread
    if thread is not None:
        return ""
    thread = threading.Thread(target=run, daemon=True)
    thread.start()


def init():
    print(f"Initialize azul")
    global azul
    random.seed(656321)
    azul = Azul(
        Supply(
            TileCollection(20, 20, 20, 20),
            TileCollection(),
            CenterTileCollection(),
            circles=[TileCollection() for _ in range(7)],
        ),
        [Player([BuildingLine(i) for i in range(1, 6)], FloorLine([]), Board()) for _ in range(3)],
    )
    supply = azul.supply.available
    for circle in azul.supply.circles:
        for _ in range(4):
            circle.add_tile(supply.take_random_tile())


init()


def main():
    init()
    generator = HTMLGenerator()
    html = generator(azul)
    html.id = "main"
    with open("output.html", "w") as f:
        f.write(html.to_html())
        f.write("\n")
        f.write('<link rel="stylesheet" href="azul.css">\n')


if __name__ == "__main__":
    main()
