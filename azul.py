import random
import re
import threading
import time
import typing
from dataclasses import asdict, field
from enum import Enum
from itertools import cycle
from typing import ClassVar, Optional, TypeAlias, cast

from tohtml import DOMNode, HTMLGenerator, HTMLTag, TextNode
from yamlplus import dataclass, yaml_object


class IllegalAction(Exception): ...


class Random(typing.Protocol):
    def randint(self, a: int, b: int) -> int: ...
    def seed(self, a: None | int | float | str | bytes | bytearray = None, version: int = 2) -> None: ...


delay = 0.0
turn_delay = delay * 5


@dataclass
class TileCollection:
    blue: int = 0
    cyan: int = 0
    red: int = 0
    yellow: int = 0
    black: int = 0

    def tile_count(self):
        return sum((getattr(self, tile.name.lower()) for tile in Tile))

    def random_tile(self, rng: Random = random) -> "Tile":
        count = self.tile_count()
        if count == 0:
            raise ValueError(f"Cannot draw from empty collection")
        rnd = rng.randint(0, count - 1)
        for tile in Tile:
            if rnd < getattr(self, tile.name.lower()):
                return tile
            rnd -= getattr(self, tile.name.lower())
        raise ValueError(f"Invalid rng")

    def empty(self) -> bool:
        return self.tile_count() == 0

    def take_random_tile(self, rng: Random = random):
        tile = self.random_tile(rng=rng)
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

    def take_random_tile(self, rng: Random = random):
        if self.available.empty():
            for tile in Tile:
                self.available.add_tile(tile, self.discarded.remove_all(tile))

        return self.available.take_random_tile(rng=rng)

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
    YELLOW = 1
    RED = 2
    BLACK = 3
    CYAN = 4
    _ignore_ = ["_abbreviation_dict"]
    _abbreviation_dict_: dict[str, "Tile"]

    @property
    def abbreviation(self) -> str:
        return "BYRKC"[self.value]

    @classmethod
    def from_abbreviation(cls, val: str):
        return cls._abbreviation_dict_[val]


Tile._abbreviation_dict_ = {tile.abbreviation: tile for tile in Tile}


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

    def is_complete(self):
        return all([tile.occupied for tile in self.tiles])

    def spot_for_color(self, color: Tile):
        for i, spot in enumerate(self.tiles):
            if spot.tile is color:
                return i, spot
        raise ValueError(f"No spot for {color}")

    def has_color(self, color: Tile):
        return self.spot_for_color(color)[1].occupied


@dataclass
class Board:
    @staticmethod
    def empty_row(index):
        return BoardLine([TileSpot(Tile((i - index) % 5)) for i in range(5)])

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
        try:
            return self.rows[row].spot_for_color(color)
        except ValueError:
            raise ValueError(f"No spot for {color} in row {row + 1}")

    def columns(self) -> list[BoardLine]:
        n = len(self.rows)
        return [BoardLine(tiles=[self.rows[j].tiles[i] for j in range(n)]) for i in range(n)]


@dataclass
class Action:
    circle: int
    row: int
    color: Tile
    _str_pattern: ClassVar[re.Pattern] = re.compile("^[A-Z][0-9][0-9]$")

    def __str__(self) -> str:
        return f"{self.color.abbreviation}{self.circle+1}{self.row+1}"

    @classmethod
    def from_str(cls, val: str):
        if not cls._str_pattern.match(val):
            raise ValueError(f"Invalid action string '{val}'")
        return Action(int(val[1]) - 1, int(val[2]) - 1, Tile.from_abbreviation(val[0]))


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
            time.sleep(delay)

        penalty, starting = self.floor_line.end_of_turn(discard_pile)
        self.score -= penalty
        time.sleep(delay)
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

    def has_complete_row(self):
        return any([row.is_complete() for row in self.board.rows])

    def get_bonus_score(self) -> int:
        """Return the bonus score this player currently gets"""
        ROW_BONUS = 2
        COLUMN_BONUS = 5
        COLOR_BONUS = 10

        bonus_score = 0

        for row in self.board.rows:
            if row.is_complete():
                bonus_score += ROW_BONUS

        for col in self.board.columns():
            if col.is_complete():
                bonus_score += COLUMN_BONUS

        for color in Tile:
            if all([row.has_color(color) for row in self.board.rows]):
                bonus_score += COLOR_BONUS

        return bonus_score

    def gain_bonus_score(self):
        self.score += self.get_bonus_score()


Round: TypeAlias = tuple[int, list[Action]]
Replay: TypeAlias = list[Round]


def raw_replay(replay: Replay) -> str:
    return ", ".join([str(action) for _, round in replay for action in round])


@dataclass
class Azul:
    supply: Supply
    players: list[Player]
    start_player: int = 0
    replay: Replay = field(default_factory=list)
    seed: None | int = None
    rng: Random = random
    _no_html_: ClassVar[list[str]] = ["replay", "seed", "rng"]

    def __post_init__(self):
        self.rng = random.Random(self.seed)

    def ordered_players(self):
        return self.players[self.start_player :] + self.players[: self.start_player]

    def end_of_turn(self):
        """Perform end of turn actions"""

        for i, player in enumerate(self.players):
            if player.end_of_turn(self.supply.discarded):
                self.start_player = i

    def start_turn(self):
        self.replay.append((self.start_player, []))
        try:
            for circle in self.supply.circles:
                for _ in range(4):
                    circle.add_tile(self.supply.take_random_tile(rng=self.rng))
        except ValueError:
            # Don't fill all circles if out of tiles
            pass
        self.supply.center.first = True

    def get_action_for_player(self, player: Player) -> Action:
        raise NotImplementedError

    def do_turn_for_player(self, player: Player):
        action = self.get_action_for_player(player)
        self.replay[-1][1].append(action)
        print(f"Action for player {player.index}: {action}")
        if action.circle == -1:
            player.get_color_from_center(action.color, action.row, self.supply.center)
        else:
            player.get_color_from_circle(
                action.color, self.supply.circles[action.circle], action.row, self.supply.center
            )
        time.sleep(turn_delay)

    def do_turn(self):
        players = cycle(self.ordered_players())
        while not (self.supply.center.empty() and all([circle.empty() for circle in self.supply.circles])):
            self.do_turn_for_player(next(players))

    def game_ended(self):
        return any([player.has_complete_row() for player in self.players])

    def play_game(self):
        """Plays a full game. Assumes start_turn() is already called once."""
        self.do_turn()
        self.end_of_turn()
        while not self.game_ended():
            self.start_turn()
            self.do_turn()
            self.end_of_turn()

        for player in self.players:
            player.gain_bonus_score()

    def format_round(self, round: Round) -> str:
        """Formats the actions of a round in columns"""
        i, actions = round
        player_count = len(self.players)
        first_turn = actions[: player_count - i]
        other_turns = [actions[j : j + player_count] for j in range(player_count - i, len(actions), player_count)]

        def format_row(turn):
            return " ".join(map(str, turn))

        return "\n".join(["    " * i + format_row(first_turn)] + [format_row(turn) for turn in other_turns])

    def format_replay(self, replay: Replay) -> str:
        """Formats the replay of a game in columns"""
        return "\n\n".join(map(self.format_round, replay))

    @staticmethod
    def initialize(player_count: int, seed: int | None = None):
        return Azul(
            Supply(
                TileCollection(20, 20, 20, 20, 20),
                TileCollection(),
                CenterTileCollection(),
                circles=[TileCollection() for _ in range(7)],
            ),
            [Player([BuildingLine(i) for i in range(1, 6)], FloorLine([]), Board(), i) for i in range(player_count)],
            seed=seed,
        )


azul: Azul | None = None
thread: threading.Thread | None = None
lock = threading.RLock()
action_selected = threading.Condition(lock)
selected_action: Optional[Action] = None


def set_action(circle: str, row: str, color: str):
    """Sets the selected action for the current human player"""
    global selected_action
    with action_selected:
        selected_action = Action(int(circle), int(row), Tile[color.upper()])
        action_selected.notify()


class HumanPlayer:
    def __init__(self, player: Player):
        self.player = player

    def get_action(self) -> Action:
        global selected_action
        with action_selected:
            selected_action = None
            action_selected.wait_for(lambda: selected_action is not None)
            assert selected_action is not None
            return selected_action


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
    azul.play_game()
    # Save replay
    with open("game.txt", "w") as f:
        f.write(f"{azul.seed}\n")
        f.write(azul.format_replay(azul.replay))
        f.write("\n")


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


def select_move(player: Player, game: Azul):
    if player.index < 0:
        return HumanPlayer(player).get_action()
    else:
        return random_legal_move(player, game)


def replay_game(seed: int, player_count: int, replay: str):
    global azul
    azul = Azul.initialize(player_count, seed)
    turns = (Action.from_str(move) for move in re.sub("[, \t\n\r]+", ",", replay).split(",") if move != "")
    azul.get_action_for_player = lambda player: next(turns)
    azul.start_turn()


def init():
    print(f"Initialize azul")
    with open("game0.txt") as f:
        seed = int(f.readline())
        replay = f.read()
    replay_game(seed, 3, replay)
    return

    global azul
    azul = Azul.initialize(3, seed=656321)
    azul.get_action_for_player = lambda player: select_move(player, cast(Azul, azul))
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
