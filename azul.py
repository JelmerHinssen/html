from dataclasses import asdict, field
from itertools import cycle, repeat
import random
import threading
import time
from typing import ClassVar, Optional, cast
from enum import Enum
import yaml

from tohtml import HTMLGenerator, DOMNode, HTMLTag, TextNode
from yamlplus import dataclass, yaml_object


class IllegalAction(Exception): ...


@dataclass
class TileCollection:
    blue: int = 0
    cyan: int = 0
    red: int = 0
    yellow: int = 0
    black: int = 0

    def tile_count(self):
        return sum((getattr(self, tile.name.lower()) for tile in Tile))

    def random_tile(self) -> "Tile":
        count = self.tile_count()
        if count == 0:
            raise ValueError(f"Cannot draw from empty collection")
        rnd = random.randint(0, count - 1)
        for tile in Tile:
            if rnd < getattr(self, tile.name.lower()):
                return tile
            rnd -= getattr(self, tile.name.lower())
        raise ValueError(f"Invalid rng")

    def empty(self) -> bool:
        return self.tile_count() == 0

    def take_random_tile(self):
        tile = self.random_tile()
        self.remove_tile(tile)
        return tile

    def remove_tile(self, tile: "Tile", count: int = 1):
        old = getattr(self, tile.name.lower())
        if old < count:
            raise ValueError(f"Collection does not have {count} {tile}(s)")
        setattr(self, tile.name.lower(), old - count)

    def add_tile(self, tile: "Tile", count: int = 1):
        setattr(self, tile.name.lower(), getattr(self, tile.name.lower()) + count)

    def __getitem__(self, tile: "Tile"):
        return getattr(self, tile.name.lower())

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

    def remove_all(self, tile: "Tile"):
        count = self[tile]
        if count <= 0:
            raise ValueError(f"Collection does not have {tile}")
        self.remove_tile(tile, count)
        return count


@dataclass
class CenterTileCollection(TileCollection):
    first: bool = True

    def to_html(self, generator: HTMLGenerator) -> list["DOMNode"]:
        children = super().to_html(generator)
        if self.first:
            children.insert(0, HTMLTag("div", classes=["tile", "tile-first"], children=[TextNode("first")]))
        return children

    def empty(self) -> bool:
        return super().empty() and not self.first


@dataclass
class Supply:
    available: TileCollection
    discarded: TileCollection
    center: CenterTileCollection
    circles: list[TileCollection]

    def take_random_tile(self):
        if self.available.empty():
            for tile in Tile:
                self.available.add_tile(tile, self.discarded.remove_all(tile))

        return self.available.take_random_tile()

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

    def end_of_turn(self, row: int, board: "Board", discard_pile: TileCollection) -> int:
        """Processes this line and returns the score gained"""
        if self.tile is None or self.count != self.length:
            return 0

        i, spot = board.spot_for_color(row, self.tile)
        if spot.occupied:
            raise ValueError(f"No spot for {self.tile} in row {row + 1}")

        discard_pile.add_tile(self.tile, self.count)
        self.tile = None
        self.count = 0

        return board.fill(row, i)


@dataclass
class FloorLine:
    tiles: list[Tile | FirstTile]

    penalty_scores: ClassVar[list[int]] = [1, 1, 2, 3, 4, 5, 6]

    def to_html(self, generator: HTMLGenerator) -> HTMLTag:
        children = []
        for tile in self.tiles:
            children.append(HTMLTag("div", classes=["tile", f"tile-{tile.name.lower()}"]))
        for _ in range(7 - len(self.tiles)):
            children.append(HTMLTag("div", classes=["tile", "tile-empty"]))
        return HTMLTag("div", children=children)

    def end_of_turn(self, discard_pile: TileCollection) -> tuple[int, bool]:
        """Clears the floor line. Computes the floor line penalty and whether the start player tile was in this line"""
        starting = False
        penalty = 0
        for i, tile in enumerate(self.tiles):
            if i < len(self.penalty_scores):
                penalty += self.penalty_scores[i]
            if tile is FirstTile.FIRST:
                starting = True
            else:
                discard_pile.add_tile(tile)
        self.tiles.clear()
        return penalty, starting


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

    @staticmethod
    def adjacent(line: list[TileSpot], index: int) -> int:
        """Return the length of the segment of the tile at given index"""
        assert line[index].occupied

        # Get start index of segment
        start = index
        while start - 1 >= 0 and line[start - 1].occupied:
            start -= 1

        # Get end index of segment
        end = index
        while end + 1 < len(line) and line[end + 1].occupied:
            end += 1

        return end - start + 1

    def adjacent_row(self, row: int, col: int) -> int:
        """Return the segment length of the row segment of the given tile"""
        return Board.adjacent(self.rows[row].tiles, col)

    def adjacent_col(self, row: int, col: int) -> int:
        """Return the segment length of the column segment of the given tile"""
        return Board.adjacent([line.tiles[col] for line in self.rows], row)

    def fill(self, row: int, col: int) -> int:
        """Fill the spot at given row and column. Return the score gained by this move"""
        spot = self.rows[row].tiles[col]
        spot.occupied = True

        row_score = self.adjacent_row(row, col)
        if row_score == 1:
            row_score = 0
        col_score = self.adjacent_col(row, col)
        if col_score == 1:
            col_score = 0

        return max(1, row_score + col_score)

    def spot_for_color(self, row: int, color: Tile):
        line = self.rows[row]
        for i, spot in enumerate(line.tiles):
            if spot.tile is color:
                return i, spot
        raise ValueError(f"No spot for {color} in row {row + 1}")


@dataclass
class Action:
    circle: int
    row: int
    color: Tile


@dataclass
class Player:
    building_lines: list[BuildingLine]
    floor_line: FloorLine
    board: Board
    index: int
    score: int = 0

    def get_color_from_circle(self, color: Tile, circle: TileCollection, row: int, center: CenterTileCollection):
        try:
            count = circle.remove_all(color)
        except ValueError:
            raise IllegalAction(f"No {color} on selected circle")
        for tile in Tile:
            left = circle[tile]
            circle.remove_tile(tile, left)
            center.add_tile(tile, left)
        self.add_tiles_to_row(color, row, count)

    def add_tiles_to_row(self, color: Tile, row: int, count: int):
        if row < 0:
            overflow = count
        else:
            line = self.building_lines[row]
            if line.tile is not None and line.tile is not color:
                raise IllegalAction(f"Cannot add {color} to line of {line.tile}")

            line.tile = color
            overflow = max(0, line.count + count - line.length)
            line.count += count - overflow
        for _ in range(overflow):
            self.floor_line.tiles.append(color)

    def get_color_from_center(self, color: Tile, row: int, center: CenterTileCollection):
        try:
            count = center.remove_all(color)
        except ValueError:
            raise IllegalAction(f"No {color} in center")
        if center.first:
            self.floor_line.tiles.append(FirstTile.FIRST)
            center.first = False
        self.add_tiles_to_row(color, row, count)

    def end_of_turn(self, discard_pile: TileCollection) -> bool:
        """
        Performs the end of turn phase including updating the score. Returns whether the player is the
        starting player next turn"""
        for i, line in enumerate(self.building_lines):
            self.score += line.end_of_turn(i, self.board, discard_pile)
            time.sleep(1)

        penalty, starting = self.floor_line.end_of_turn(discard_pile)
        self.score -= penalty
        time.sleep(1)
        return starting

    def legal_rows_for_color(self, color: Tile, filter_floor: bool):
        if not filter_floor:
            yield -1
        for i, line in enumerate(self.building_lines):
            if line.tile is None:
                if self.board.spot_for_color(i, color)[1].occupied:
                    continue
            elif line.tile is not color:
                continue
            elif line.count >= line.length:
                continue
            yield i

    def legal_moves(self, game: "Azul", filter_floor: bool = True):
        def moves_for_collection(index, circle):
            for tile in Tile:
                if circle[tile] == 0:
                    continue
                for row in self.legal_rows_for_color(tile, filter_floor):
                    yield Action(index, row, tile)

        for i, circle in enumerate(game.supply.circles):
            yield from moves_for_collection(i, circle)

        yield from moves_for_collection(-1, game.supply.center)

    def all_moves(self, game: "Azul"):
        generator = self.legal_moves(game, True)
        try:
            first = next(generator)
            yield first
            yield from generator
        except StopIteration:
            yield from self.legal_moves(game, False)


@dataclass
class Azul:
    supply: Supply
    players: list[Player]
    start_player: int = 0

    def ordered_players(self):
        return self.players[self.start_player :] + self.players[: self.start_player]

    def end_of_turn(self):
        """Perform end of turn actions"""

        for i, player in enumerate(self.players):
            if player.end_of_turn(self.supply.discarded):
                self.start_player = i

    def start_turn(self):
        try:
            for circle in self.supply.circles:
                for _ in range(4):
                    circle.add_tile(self.supply.take_random_tile())
        except ValueError:
            # Don't fill all circles if out of tiles
            pass
        self.supply.center.first = True

    def get_action_for_player(self, player: Player) -> Action:
        raise NotImplementedError

    def do_turn_for_player(self, player: Player):
        action = self.get_action_for_player(player)
        print(f"Action for player {player.index}: {action}")
        if action.circle == -1:
            player.get_color_from_center(action.color, action.row, self.supply.center)
        else:
            player.get_color_from_circle(
                action.color, self.supply.circles[action.circle], action.row, self.supply.center
            )
        time.sleep(1)

    def do_turn(self):
        players = cycle(self.ordered_players())
        while not (self.supply.center.empty() and all([circle.empty() for circle in self.supply.circles])):
            self.do_turn_for_player(next(players))


azul: Azul | None = None
thread: threading.Thread | None = None


def get_state():
    if not azul:
        return "<h2>uh oh</h2>"
    generator = HTMLGenerator()
    html = generator(azul)
    html.id = "main"
    return html.to_html() + f"\n"


turns = [
    Action(1, 2, Tile.RED),
    Action(0, 0, Tile.BLUE),
    Action(-1, 1, Tile.CYAN),
    Action(2, 0, Tile.BLUE),
    Action(-1, 2, Tile.CYAN),
    Action(3, 0, Tile.CYAN),
    Action(-1, 1, Tile.YELLOW),
    Action(-1, 4, Tile.RED),
    Action(6, 2, Tile.CYAN),
    Action(4, 3, Tile.YELLOW),
    Action(5, 4, Tile.RED),
    Action(-1, 3, Tile.CYAN),
    Action(-1, 4, Tile.BLUE),
    Action(-1, 4, Tile.RED),
    Action(-1, 4, Tile.YELLOW),
]


def run():
    global azul
    assert azul is not None
    for _ in range(5):
        azul.do_turn()
        azul.end_of_turn()
        azul.start_turn()


def start():
    global thread
    if thread is not None:
        return ""
    thread = threading.Thread(target=run, daemon=True)
    thread.start()


def random_legal_move(player: Player, game: Azul):
    moves = list(player.all_moves(game))
    rnd = random.randint(0, len(moves) - 1)
    return moves[rnd]


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
        [Player([BuildingLine(i) for i in range(1, 6)], FloorLine([]), Board(), i) for i in range(3)],
    )
    turn = cycle(turns)
    azul.get_action_for_player = lambda player: random_legal_move(player, cast(Azul, azul))
    azul.start_turn()


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
