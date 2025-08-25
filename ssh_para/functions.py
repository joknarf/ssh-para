import os
import curses
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

def decode_line(line: bytes) -> str:
    """try decode line exception on binary"""
    try:
        return line.decode()
    except UnicodeDecodeError:
        return ""


def last_line(fd: BufferedReader, maxline: int = 1000) -> str:
    """last non empty line of file"""
    line = "\n"
    fd.seek(0, os.SEEK_END)
    size = 0
    while line in ["\n", "\r"] and size < maxline:
        try:  # catch if file empty / only empty lines
            while fd.read(1) not in [b"\n", b"\r"]:
                fd.seek(-2, os.SEEK_CUR)
                size += 1
        except OSError:
            fd.seek(0)
            line = decode_line(fd.readline())
            break
        line = decode_line(fd.readline())
        fd.seek(-4, os.SEEK_CUR)
    return line.strip()
