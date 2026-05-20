"""Mock tool for Day 4. Hardcoded payoff matrices for three 2x2 games.

get_payoff_matrix(game_name) -> {"row_actions", "col_actions", "matrix"}.
matrix[i][j] is [row_player_payoff, col_player_payoff] for row action i and
col action j. Numeric values are plain ints so the result is trivially
JSON-serializable; the wrapper feeds the dict back to the model as a
role:"tool" message.
"""

_GAMES = {
    "prisoners_dilemma": {
        "row_actions": ["cooperate", "defect"],
        "col_actions": ["cooperate", "defect"],
        "matrix": [[[3, 3], [0, 5]],
                   [[5, 0], [1, 1]]],
    },
    "stag_hunt": {
        "row_actions": ["stag", "hare"],
        "col_actions": ["stag", "hare"],
        "matrix": [[[4, 4], [0, 3]],
                   [[3, 0], [2, 2]]],
    },
    "matching_pennies": {
        "row_actions": ["heads", "tails"],
        "col_actions": ["heads", "tails"],
        "matrix": [[[1, -1], [-1, 1]],
                   [[-1, 1], [1, -1]]],
    },
}


def get_payoff_matrix(game_name):
    if game_name not in _GAMES:
        raise ValueError(f"unknown game_name: {game_name!r}; "
                         f"known: {sorted(_GAMES)}")
    return _GAMES[game_name]
