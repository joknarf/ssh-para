import os
import curses
import re
from typing import Optional
from io import BufferedReader

CURSES_COLORS = {
    "RUNNING": 100,
    "SUCCESS": 102,
    "FAILED": 104,
    "ABORTED": 104,
    "KILLED": 104,
    "TIMEOUT": 104,
    "IDLE": 106,
    "GAUGE": 108,
    "HOST": 110,
}
ANSI_ESCAPE = re.compile(br'(\x1B\[\??([0-9]{1,2};){0,4}[0-9]{1,3}[m|Klh]|\x1B\[[0-9;]*[mGKHF])')

def strip_ansi(text):
    """Remove ANSI and control characters from the text."""
    return ANSI_ESCAPE.sub(b'', text)

def curses_init_pairs() -> None:
        status_color = CURSES_COLORS
        curses.init_pair(
            status_color["RUNNING"], curses.COLOR_WHITE, curses.COLOR_BLUE
        )
        curses.init_pair(
            status_color["RUNNING"] + 1, curses.COLOR_BLUE, curses.COLOR_BLACK
        )
        curses.init_pair(
            status_color["SUCCESS"], curses.COLOR_WHITE, curses.COLOR_GREEN
        )
        curses.init_pair(
            status_color["SUCCESS"] + 1, curses.COLOR_GREEN, curses.COLOR_BLACK
        )
        curses.init_pair(
            status_color["FAILED"], curses.COLOR_WHITE, curses.COLOR_RED
        )
        curses.init_pair(
            status_color["FAILED"] + 1, curses.COLOR_RED, curses.COLOR_BLACK
        )
        curses.init_pair(status_color["IDLE"], curses.COLOR_WHITE, 8)
        curses.init_pair(status_color["IDLE"] + 1, 8, curses.COLOR_BLACK)
        curses.init_pair(status_color["GAUGE"], 8, curses.COLOR_BLUE)
        curses.init_pair(status_color["HOST"], curses.COLOR_YELLOW, curses.COLOR_BLACK)


def addstr(stdscr: Optional["curses._CursesWindow"], *args, **kwargs) -> None:
    """curses addstr w/o exception"""
    if stdscr:
        try:
            stdscr.addstr(*args, **kwargs)
        except (curses.error, ValueError):
            pass


def addstrc(stdscr: Optional["curses._CursesWindow"], *args, **kwargs) -> None:
    """curses addstr and clear eol"""
    if stdscr:
        addstr(stdscr, *args, **kwargs)
        stdscr.clrtoeol()

def last_line(fd: BufferedReader, maxline: int = 1000) -> str:
    """last non empty line of file"""
    line = b"\n"
    fd.seek(0, os.SEEK_END)
    size = 0
    while line in [b"\n", b"\r"] and size < maxline:
        try:  # catch if file empty / only empty lines
            while fd.read(1) not in [b"\n", b"\r"]:
                fd.seek(-2, os.SEEK_CUR)
                size += 1
        except OSError:
            fd.seek(0)
            line = fd.readline()
            break
        line = fd.readline()
        try:
            fd.seek(-4, os.SEEK_CUR)
        except OSError:
            break
    return strip_ansi(line).decode(errors="ignore").strip()
