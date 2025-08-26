#!/usr/bin/env python3
"""Reusable Segment (powerline-style) header for curses UIs."""

import curses
from typing import Optional
from ssh_para.functions import addstr
from ssh_para.symbols import SYMBOL_BEGIN, SYMBOL_END


class Segment:
    """display of colored powerline style"""

    def __init__(
        self,
        stdscr: "curses._CursesWindow",
        nbsegments: int,
        bg: Optional[list] = None,
        fg: Optional[list] = None,
        style: Optional[list] = None,
        seg1: bool = True,
    ) -> None:
        self.stdscr = stdscr
        self.segments = []
        self.nbsegments = nbsegments
        fg = fg or [curses.COLOR_WHITE] * nbsegments
        bg = bg or [
            curses.COLOR_BLUE,
            curses.COLOR_GREEN,
            curses.COLOR_RED,
            8,
            curses.COLOR_MAGENTA,
            curses.COLOR_CYAN,
            curses.COLOR_BLACK,
        ]
        # ensure bg has at least nbsegments+1 entries
        if len(bg) <= nbsegments:
            bg = bg + [curses.COLOR_BLACK] * (nbsegments + 1 - len(bg))
        try:
            bg[nbsegments] = curses.COLOR_BLACK
        except Exception:
            pass
        self.st = style or ["NORMAL"] * nbsegments
        self.seg1 = seg1
        # initialize color pairs safely
        try:
            curses.init_pair(1, bg[0], curses.COLOR_BLACK)
            for i in range(0, nbsegments):
                curses.init_pair(i * 2 + 2, fg[i], bg[i])
                curses.init_pair(i * 2 + 3, bg[i], bg[i + 1])
        except Exception:
            # terminal may not support colors yet; ignore
            pass

    def set_segments(self, x: int, y: int, segments: list) -> None:
        """display powerline-like segments on one line at (y,x)"""
        # Draw left glyph
        try:
            addstr(self.stdscr, y, x, SYMBOL_BEGIN, curses.color_pair(1))
        except Exception:
            addstr(self.stdscr, y, x, SYMBOL_BEGIN)
        curx = x + 1
        for i, segment in enumerate(segments):
            try:
                attr = curses.color_pair(i * 2 + 2)
            except Exception:
                attr = None
            text = f" {segment} "
            addstr(self.stdscr, y, curx, text, attr)
            curx += len(text)
            try:
                end_attr = curses.color_pair(i * 2 + 3)
            except Exception:
                end_attr = None
            addstr(self.stdscr, y, curx, SYMBOL_END, end_attr)
            curx += len(SYMBOL_END)
        try:
            self.stdscr.clrtoeol()
        except Exception:
            pass
