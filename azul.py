from dataclasses import field
import random
from typing import Optional
from enum import Enum
import yaml

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


@dataclass
class CenterTileCollection(TileCollection):
    first: bool = True


@dataclass
class Supply:
    available: TileCollection
    discarded: TileCollection
    center: CenterTileCollection
    circles: list[TileCollection]


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


@dataclass
class FloorLine:
    tiles: list[Tile]


@dataclass
class TileSpot:
    tile: Tile
    occupied: bool = False


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


def main():
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

    azul.players[0].floor_line.tiles.append(supply.take_random_tile())

    with open("output.txt", "w") as f:
        f.write(repr(azul))
    with open("output.yaml", "w") as f:
        yaml.dump(azul, f, sort_keys=False)

    with open("output.yaml") as f:
        obj = yaml.load(f, yaml.Loader)

    with open("output2.txt", "w") as f:
        f.write(repr(obj))

    with open("output2.yaml", "w") as f:
        yaml.dump(obj, f, sort_keys=False)


if __name__ == "__main__":
    main()
