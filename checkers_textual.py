from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, RichLog, Static

SAVE_FILE = str(Path.home() / ".config/checkers_save.json")

BOARD_SIZE = 8
WHITE = 'w'  # Гравець
BLACK = 'b'  # ШІ
WHITE_KING = 'W'
BLACK_KING = 'B'
EMPTY = " "


class CheckersWidget(Horizontal):
    """Віджет шашок із полем можливих ходів праворуч."""

    def __init__(self, id: str | None = None):
        super().__init__(id=id)
        loaded_board, loaded_turn = self.load_game()
        if loaded_board:
            self.board = loaded_board
            self.turn = loaded_turn
        else:
            self.board = self.create_board()
            self.turn = WHITE
        self.current_moves = []

    def compose(self) -> ComposeResult:
        # Ліва колонка: дошка
        with Vertical(classes="checkers-left-pane"):
            yield Label("ШАШКИ (Англійські)", classes="checkers-title")
            yield Static(id="checkers-board-view")
        
        # Права колонка: можливі ходи, лог, поле введення та кнопки
        with Vertical(classes="checkers-right-pane"):
            yield Label("МОЖЛИВІ ХОДИ", classes="checkers-subtitle")
            # Використовуємо VerticalScroll, щоб нічого не зникало і можна було прокручувати список ходів
            with VerticalScroll(id="checkers-moves-scroll"):
                yield RichLog(id="checkers-log", highlight=True, markup=True)
            
            yield Input(placeholder="Номер ходу (0, 1...), 's', '?'", id="checkers-input")
            with Horizontal(classes="checkers-buttons"):
                yield Button("Зберегти", id="chk-save")
                yield Button("Нова гра", id="chk-reset", variant="error")

    def on_mount(self) -> None:
        self.update_view()
        self.query_one("#checkers-input", Input)

    def save_game(self, board, turn):
        data = {"board": board, "turn": turn}
        try:
            Path(SAVE_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(SAVE_FILE, "w") as f:
                json.dump(data, f)
            self.log_message("[green][СИСТЕМА] Гру збережено![/green]")
        except Exception as e:
            self.log_message(f"[red]Помилка збереження: {e}[/red]")

    def load_game(self):
        if not os.path.exists(SAVE_FILE):
            return None, None
        try:
            with open(SAVE_FILE, "r") as f:
                data = json.load(f)
            return data["board"], data["turn"]
        except Exception:
            return None, None

    def to_chess_coords(self, row, col):
        letters = "ABCDEFGH"
        return f"{letters[col]}{8 - row}"

    def create_board(self):
        board = [[EMPTY for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if (r + c) % 2 != 0:
                    if r < 3: board[r][c] = BLACK
                    elif r > 4: board[r][c] = WHITE
        return board

    def get_all_moves(self, board, player):
        moves = []
        jumps = []
        is_white = player.lower() == 'w'
        enemies = [BLACK, BLACK_KING] if is_white else [WHITE, WHITE_KING]
        directions = [(-1, -1), (-1, 1), (1, -1), (1, 1)]

        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if board[r][c].lower() == player[0].lower():
                    piece = board[r][c]
                    is_king = piece in [WHITE_KING, BLACK_KING]
                    
                    for dr, dc in directions:
                        if not is_king:
                            if is_white and dr > 0: continue
                            if not is_white and dr < 0: continue
                        
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                            if board[nr][nc] == EMPTY:
                                moves.append(((r, c), (nr, nc)))
                        
                        jr, jc = r + 2*dr, c + 2*dc
                        if 0 <= jr < BOARD_SIZE and 0 <= jc < BOARD_SIZE:
                            if board[nr][nc] in enemies and board[jr][jc] == EMPTY:
                                jumps.append(((r, c), (jr, jc), (nr, nc)))
        return jumps if jumps else moves

    def make_move(self, board, move):
        new_board = copy.deepcopy(board)
        start, end = move[0], move[1]
        piece = new_board[start[0]][start[1]]
        new_board[end[0]][end[1]] = piece
        new_board[start[0]][start[1]] = EMPTY
        if len(move) == 3:
            new_board[move[2][0]][move[2][1]] = EMPTY
        if piece == WHITE and end[0] == 0: new_board[end[0]][end[1]] = WHITE_KING
        if piece == BLACK and end[0] == 7: new_board[end[0]][end[1]] = BLACK_KING
        return new_board

    def evaluate(self, board):
        score = 0
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if board[r][c] == BLACK: score += 10
                elif board[r][c] == BLACK_KING: score += 20
                elif board[r][c] == WHITE: score -= 10
                elif board[r][c] == WHITE_KING: score -= 20
        return score

    def minimax(self, board, depth, alpha, beta, maximizing_player):
        if depth == 0: return self.evaluate(board), None
        player = BLACK if maximizing_player else WHITE
        moves = self.get_all_moves(board, player)
        if not moves: return self.evaluate(board), None
        
        best_move = None
        if maximizing_player:
            v = float('-inf')
            for m in moves:
                ev = self.minimax(self.make_move(board, m), depth-1, alpha, beta, False)[0]
                if ev > v: v, best_move = ev, m
                alpha = max(alpha, v)
                if beta <= alpha: break
            return v, best_move
        else:
            v = float('inf')
            for m in moves:
                ev = self.minimax(self.make_move(board, m), depth-1, alpha, beta, True)[0]
                if ev < v: v, best_move = ev, m
                beta = min(beta, v)
                if beta <= alpha: break
            return v, best_move

    def log_message(self, text: str) -> None:
        log = self.query_one("#checkers-log", RichLog)
        log.write(text)

    
    def update_view(f_self) -> None:
        lines = ["[b]A   B   C   D   E   F   G   H[/b]"]
        lines.append(" ")
        for r in range(BOARD_SIZE):
            row_str = f"  [b]{8 - r}[/b]   "
            for c in range(BOARD_SIZE):
                piece = f_self.board[r][c]
                if piece == WHITE:
                    row_str += "⛀   "
                elif piece == WHITE_KING:
                    row_str += "⭔   "
                elif piece == BLACK:
                    row_str += "⛂   "
                elif piece == BLACK_KING:
                    row_str += "⭓   "
                else:
                    row_str += "·   "
            row_str += f" [b]{8 - r}[/b] "
            lines.append(row_str)
        lines.append(" ")
        lines.append("[b]A   B   C   D   E   F   G   H[/b]")

        board_view = f_self.query_one("#checkers-board-view", Static)
        board_view.update("\n".join(lines))

        f_self.current_moves = f_self.get_all_moves(f_self.board, f_self.turn)
        
        if not f_self.current_moves:
            f_self.log_message(f"\n[bold red]КІНЕЦЬ ГРИ! Перемогли {'Чорні' if f_self.turn == WHITE else 'Білі'}[/bold red]")
            if os.path.exists(SAVE_FILE): os.remove(SAVE_FILE)
            return

        if f_self.turn == WHITE:
            f_self.log_message("\n[bold]--- ВАШ ХІД (Білі) ---[/bold]")
            for i, m in enumerate(f_self.current_moves):
                start = f_self.to_chess_coords(m[0][0], m[0][1])
                end = f_self.to_chess_coords(m[1][0], m[1][1])
                is_jump = '(БИТТЯ!)' if len(m) == 3 else ''
                f_self.log_message(f"[cyan]{i}: {start} -> {end} {is_jump}[/cyan]")
        else:
            f_self.log_message("\n[yellow]ШІ думає...[/yellow]")
            score, move = f_self.minimax(f_self.board, 4, float('-inf'), float('inf'), True)
            if move is not None:
                f_self.board = f_self.make_move(f_self.board, move)
                f_self.log_message(f"ШІ зробив хід: {f_self.to_chess_coords(move[0][0], move[0][1])} -> {f_self.to_chess_coords(move[1][0], move[1][1])}")
                f_self.turn = WHITE
                f_self.update_view()
            else:
                f_self.log_message("\n[green]ШІ не знайшов варіантів і здається![/green]")


    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "checkers-input":
            return
        
        val = event.value.strip().lower()
        event.input.value = ""

        if val == '?':
            self.log_message("\n[yellow]ПРАВИЛА: Звичайні ходять/б'ють вперед, дамки — у всі боки. Обов'язкове взяття![/yellow]")
            return
        if val == 's':
            self.save_game(self.board, self.turn)
            return

        try:
            idx = int(val)
            if 0 <= idx < len(self.current_moves):
                self.board = self.make_move(self.board, self.current_moves[idx])
                self.turn = BLACK
                self.update_view()
            else:
                self.log_message(f"[red]Помилка: введіть номер від 0 до {len(self.current_moves)-1}[/red]")
        except ValueError:
            self.log_message("[red]Помилка: введіть число, 's' або '?'[/red]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "chk-save":
            self.save_game(self.board, self.turn)
        elif event.button.id == "chk-reset":
            self.board = self.create_board()
            self.turn = WHITE
            if os.path.exists(SAVE_FILE): os.remove(SAVE_FILE)
            self.update_view()
            self.log_message("[yellow]Нову гру розпочато![/yellow]")
