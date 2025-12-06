#!/usr/bin/env python3
"""Simple curses TUI to browse ssh-para log directory.

Features:
- list jobs from a run directory (scan *.out files)
- filter by command substring, by status, and by output text
- open a job output with Enter
- keys: up/down, j/k, / (output search), n (name search), s (cycle status), r (reset), q (quit)
"""

import curses
import os
import re
from glob import glob
from typing import List, Dict, Optional
from .functions import addstr, curses_init_pairs, last_line, strip_ansi, CURSES_COLORS
from .segment import Segment
from .symbols import SYMBOL_BEGIN, SYMBOL_END

STATUSES = ["ALL", "SUCCESS", "FAILED", "TIMEOUT", "KILLED", "ABORTED"]

def _read_tail(path: str, maxbytes: Optional[int] = None) -> str:
    try:
        with open(path, "rb") as fd:
            if maxbytes:
                fd.seek(0, os.SEEK_END)
                size = fd.tell()
                start = max(0, size - maxbytes)
                fd.seek(start)
            data = fd.read()
        try:
            return data.decode(errors="ignore").strip()
        except Exception:
            return ""
    except OSError:
        return ""

def read_status_names(dirlog: str, file: str) -> List:
    fpath = os.path.join(dirlog, file)
    if os.path.exists(fpath):
        with open(fpath, 'r') as f:
            return f.read().splitlines()
    return []

def load_jobs(dirlog: str) -> List[Dict]:
    """Scan dirlog for job output files and build job entries."""
    names_status = {}
    for name in read_status_names(dirlog, "killed.status"):
        names_status[name] = 'KILLED'
    for name in read_status_names(dirlog, "timeout.status"):
        names_status[name] = 'TIMEOUT'
    for name in read_status_names(dirlog, "success.status"):
        names_status[name] = 'SUCCESS'

    files = glob(os.path.join(dirlog, "*.out"))
    jobs: List[Dict] = []
    for f in sorted(files):
        name = os.path.splitext(os.path.basename(f))[0]
        # skip global files
        if name.startswith("ssh-para"):
            continue
        status = "RUNNING"
        exit_code = ""
        if name in names_status:
            status = names_status[name]
        else:
            failed = os.path.join(dirlog, f"{name}.failed")
            if os.path.exists(failed):
                status = "FAILED"
                with open(failed, "r", encoding="utf-8", errors="replace") as fd:
                    exit_code = fd.read().strip().split()[2]
        if status in ["ABORTED", "TIMEOUT", "KILLED"]:
            exit_code = "255"
        elif status == "SUCCESS":
            exit_code = "0"
        with open(f, "rb") as fd:
            snippet = last_line(fd)
        jobs.append({
            "name": name,
            "status": status,
            "exit_code": exit_code,
            # "cmd": cmd or "",
            "snippet": snippet,
        })
    aborted = os.path.join(dirlog, "aborted.status")
    if os.path.exists(aborted):
        with open(aborted, 'r') as f:
            for name in f.read().splitlines():
                jobs.append({"name": name, "status": "ABORTED", "exit_code": "-1", "snippet": "canceled run"})
    return jobs


def parse_result(dirlog: str) -> Dict[str, str]:
    """Parse ssh-para.result file and return key summary values."""
    result_file = os.path.join(dirlog, "ssh-para.result")
    summary: Dict[str, str] = {"end": "--:--:--"}

    if not os.path.isfile(result_file):
        return summary
    try:
        with open(result_file, "r", encoding="utf-8", errors="replace") as fd:
            text = fd.read()
    except OSError:
        return summary
    # extract basic fields

    m = re.search(r"begin:\s*([0-9\- :]+)", text)
    if m:
        summary["begin"] = m.group(1).strip()
    m = re.search(r"end:\s*([0-9\- :]+)", text)
    if m:
        summary["end"] = m.group(1).strip()
    m = re.search(r"dur:\s*([0-9:\.]+)", text)
    if m:
        summary["dur"] = m.group(1).strip()
    m = re.search(r"runs:\s*([0-9]+\s*/\s*[0-9]+)", text, re.IGNORECASE)
    if m:
        summary["runs"] = m.group(1).strip()
        summary["runs_total"] = summary["runs"].split("/")[1].strip()
    # counts
    for k in ("success", "failed", "timeout", "killed", "aborted"):
        m = re.search(rf"{k}:\s*([0-9]+)", text)
        if m:
            summary[k] = m.group(1)
    return summary


class Tui:
    status_color = CURSES_COLORS
    COLOR_HOST = CURSES_COLORS["HOST"]

    def __init__(self, stdscr, dirlog: str):
        self.stdscr = stdscr
        self.dirlog = dirlog
        self.jobs = load_jobs(dirlog)
        self.summary = parse_result(dirlog)
        self.counts = self.summary.copy()
        self.name_filter = ""
        self.text_filter = ""
        self.name_re = None
        self.text_re = None
        self.name_neg = False
        self.text_neg = False
        self.status_idx = 0
        self.cursor = 0
        self.top = 0
        self.filtered_jobs: Optional[List[Dict]] = None
        self.statuses = ["ALL"]
        self.init_color()
        try:
            with open(os.path.join(dirlog, "ssh-para.command"), "r", encoding="utf-8", errors="replace") as fd:
                self.command = fd.read().strip().split("Command: ")[-1].split("\n")[0]
        except Exception:
            self.command = ""

    def count(self, job: Dict) -> None:
        if job["status"] != "ABORTED":
            self.counts["runs"] += 1
        if job["status"] == "SUCCESS":
            self.counts["success"] += 1
        elif job["status"] not in ["RUNNING", "ABORTED"]:
            self.counts["failed"] += 1

    def filtered(self) -> List[Dict]:
        if self.filtered_jobs is not None:
            return self.filtered_jobs
        self.counts = {"runs": 0, "success": 0, "failed": 0}
        s = self.statuses[self.status_idx]
        res = []
        for j in self.jobs:
            if j["status"] not in self.statuses:
                self.statuses.append(j['status'])
            if s != "ALL" and j["status"] != s:
                continue
            # Command filter: regex (compiled), fall back to substring if empty
            if self.name_filter:
                if bool(self.name_re.search(j["name"] or "")) == self.name_neg:
                    continue
            if self.text_filter:
                hay = j["snippet"] or ""
                # filter: try snippet first, then tail
                matched = False
                matched_line = None
                if self.text_re.search(hay):
                    matched = True
                    matched_line = hay
                else:
                    outfile = os.path.join(self.dirlog, f"{j['name']}.out")
                    with open(outfile, "r", encoding="utf-8") as f:
                        for line in f:
                            if self.text_re.search(line):
                                matched = True
                                matched_line = line
                                break
                if matched == self.text_neg:
                    continue
                j2 = j.copy()
                if not self.text_neg:
                    j2["snippet"] = (matched_line or "").strip()
                res.append(j2)
                self.count(j2)
                continue
            res.append(j)
            self.count(j)
        self.filtered_jobs = res
        return res

    def init_color(self) -> None:
        curses.start_color()
        curses.init_pair(20, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses_init_pairs()
        self.segment = Segment(self.stdscr, 6)

    def draw(self, items: Optional[List[Dict]] = None) -> None:
        self.stdscr.erase()
        maxy, maxx = self.stdscr.getmaxyx()
        # summary line from ssh-para.result (display first if present)
        sumline = [
            f"runs: {self.counts['runs']}/{self.summary.get('runs_total', '?')}",
            f"success: {self.counts['success']}",
            f"failed: {self.counts['failed']}",
            f"begin: {self.summary.get('begin', '')}",
            f"end: {self.summary.get('end', '')}",
            f"dur: {self.summary.get('dur', '')}"
        ]

        # draw using Segment
        try:
            self.segment.set_segments(0, 0, sumline)
        except Exception:
            self.stdscr.addnstr(0, 0, " | ".join(sumline), maxx - 1)
        first_item_line = 3
        header = f"Filters: status={self.statuses[self.status_idx]} name='{self.name_filter}' text='{self.text_filter}' cmd={self.command}"
        self.stdscr.addnstr(1, 0, header, maxx - 1)
    # items already ensured above
        if not items:
            self.stdscr.addnstr(first_item_line, 0, "No matching jobs", maxx - 1)
            self.stdscr.refresh()
            return
        # display list
        avail = (maxy - 2) - first_item_line
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + avail:
            self.top = self.cursor - avail + 1
        for idx in range(self.top, min(len(items), self.top + avail)):
            row = idx - self.top + first_item_line
            j = items[idx]
            marker = "►" if idx == self.cursor else " "
            addstr(self.stdscr, row, 0, f"{marker} {j['name'][:20]:20} ", curses.color_pair(self.COLOR_HOST))
            self.print_status(j["status"])
            addstr(self.stdscr, f" {j['exit_code']:>3} {j['snippet'][:maxx - 40]}")
        # footer
        self.stdscr.addnstr(maxy - 1, 0, "[q]uit [/]log filter [n]ame filter [s]tatus cycle [r]eset [p]rint [Enter]view", maxx - 1)
        self.stdscr.refresh()

    def prompt(self, prompt: str) -> str:
        curses.echo()
        maxy, maxx = self.stdscr.getmaxyx()
        self.stdscr.addnstr(maxy - 2, 0, " " * (maxx - 1), maxx - 1)
        self.stdscr.addnstr(maxy - 2, 0, prompt, maxx - 1)
        self.stdscr.refresh()
        try:
            s = self.stdscr.getstr(maxy - 2, len(prompt), maxx - len(prompt) - 1)
            if isinstance(s, bytes):
                s = s.decode(errors="replace")
        except Exception:
            s = ""
        curses.noecho()
        return s.strip()

    def print_status(self, status: str) -> None:
        """print thread status"""
        color = self.status_color[status]
        addstr(self.stdscr, SYMBOL_BEGIN, curses.color_pair(color + 1))
        addstr(self.stdscr, f" {status:8} ", curses.color_pair(color))
        addstr(self.stdscr, SYMBOL_END, curses.color_pair(color + 1))

    def view_output(self, job: Dict) -> None:
        # open a simple fullscreen viewer
        maxy, maxx = self.stdscr.getmaxyx()
        re_r = re.compile(br"\n.*\r")
        try:
            outfile = os.path.join(self.dirlog, f"{job['name']}.out")
            with open(outfile, "rb") as fd:
                lines = strip_ansi(re_r.sub(b"\n", fd.read())).decode(errors="ignore").splitlines()
        except OSError:
            lines = ["(no output file)"]
        pos = 0
        # search state (default to list-view text search if present)
        search_re = self.text_re if hasattr(self, "text_re") else None
        matches: List[int] = []
        match_idx = -1
        if search_re is not None:
            # precompute matches for this job
            try:
                matches = [i for i, L in enumerate(lines) if search_re.search(L)]
                match_idx = 0 if matches else -1
                if match_idx >= 0:
                    h = maxy - 2
                    pos = max(0, matches[match_idx] - h // 2)
            except Exception:
                # any issue compiling/searching: clear
                search_re = None
                matches = []
                match_idx = -1
        # prepare highlight attribute
        try:
            hl_attr = curses.color_pair(20) | curses.A_BOLD
        except Exception:
            hl_attr = curses.A_REVERSE
        while True:
            self.stdscr.erase()
            h = maxy - 2
            for i in range(h):
                if pos + i >= len(lines):
                    break
                try:
                    text = lines[pos + i]
                    if search_re:
                        col = 0
                        last = 0
                        for m in search_re.finditer(text):
                            if last < m.start():
                                seg = text[last:m.start()]
                                try:
                                    # print normal segment
                                    self.stdscr.addnstr(i, col, seg, maxx - col - 1)
                                except curses.error:
                                    pass
                                col += len(seg)
                            # print highlighted match
                            match_text = text[m.start(): m.end()]
                            try:
                                self.stdscr.addnstr(i, col, match_text, maxx - col - 1, hl_attr)
                            except curses.error:
                                pass
                            col += len(match_text)
                            last = m.end()
                        # trailing
                        if last < len(text):
                            tail = text[last:]
                            try:
                                self.stdscr.addnstr(i, col, tail, maxx - col - 1)
                            except curses.error:
                                pass
                    else:
                        try:
                            self.stdscr.addnstr(i, 0, text, maxx - 1)
                        except curses.error:
                            pass
                except curses.error:
                    pass
            # footer shows search status when active
            search_info = ""
            if search_re is not None:
                total = len(matches)
                cur = match_idx + 1 if match_idx >= 0 else 0
                search_info = f"  /{search_re.pattern}/ {cur}/{total}"
            footer = f"{job['name']}  status:{job['status']}{search_info}  [q]uit [/]search [n]ext [p]rev [r]eset"
            self.stdscr.addnstr(maxy - 1, 0, footer, maxx - 1)
            self.stdscr.refresh()
            ch = self.stdscr.getch()
            if ch in (ord('q'), 27):
                break
            if ch in (ord('j'), curses.KEY_DOWN):
                if pos + h < len(lines):
                    pos += 1
            if ch in (ord('k'), curses.KEY_UP):
                if pos > 0:
                    pos -= 1
            if ch in (curses.KEY_NPAGE, 6):
                pos = min(pos + h, max(0, len(lines) - h))
            if ch in (curses.KEY_PPAGE, 2):
                pos = max(0, pos - h)
            if ch in (curses.KEY_HOME, ord('0')):
                pos = 0 
            if ch == curses.KEY_END or ch == ord('G'):
                pos = max(0, len(lines) - h)
            if ch == ord('/'):
                # prompt for a regexp and compile
                expr = self.prompt("Search regexp: ")
                if expr:
                    try:
                        search_re = re.compile(expr, re.IGNORECASE)
                        # build match list (indices of matching lines)
                        matches = [i for i, L in enumerate(lines) if search_re.search(L)]
                        if matches:
                            match_idx = 0
                            # position viewer so matched line is visible
                            pos = max(0, matches[match_idx] - h // 2)
                        else:
                            match_idx = -1
                    except re.error:
                        search_re = None
                        matches = []
                        match_idx = -1
                else:
                    # empty expression clears search
                    search_re = None
                    matches = []
                    match_idx = -1
            if ch == ord('n') and matches:
                match_idx = (match_idx + 1) % len(matches)
                pos = max(0, matches[match_idx] - h // 2)
            if ch == ord('p') and matches:
                match_idx = (match_idx - 1) % len(matches)
                pos = max(0, matches[match_idx] - h // 2)
            if ch == ord('r'):
                search_re = None
                matches = []
                match_idx = -1

    def init_curses(self) -> None:
        """ (Re)initialize curses state after temporarily exiting to console."""
        try:
            self.stdscr = curses.initscr()
            curses.cbreak()
            curses.noecho()
            curses.curs_set(0)
            self.init_color()
        except Exception:
            pass

    def show_names_console(self) -> None:
        """Temporarily exit curses, print job names to stdout, wait for one key, then re-enter curses."""
        # End curses mode to allow normal stdout
        try:
            curses.endwin()
        except Exception:
            pass
        # print only the currently filtered jobs so output matches TUI view
        items = self.filtered()
        print()
        print("Jobs (filtered):")
        for j in items:
            print(j.get("name", ""))
        print()
        # show active filters for context
        print(f"Filters: status={self.statuses[self.status_idx]} name='{self.name_filter}' text='{self.text_filter}' cmd={getattr(self, 'command', '')}")
        input("Press Enter to return to TUI...")
        # Reinitialize curses state
        self.init_curses()
    
    def loop(self) -> None:
        curses.curs_set(0)
        first_item_line = 3
        while True:
            items = self.filtered()
            items_len = len(items)
            self.draw(items)
            ch = self.stdscr.getch()
            if ch in (ord('q'), 27):
                break
            elif ch in (curses.KEY_DOWN, ord('j')):
                if self.cursor + 1 < items_len:
                    self.cursor += 1
            elif ch in (curses.KEY_UP, ord('k')):
                if self.cursor > 0:
                    self.cursor -= 1
            elif ch in (curses.KEY_NPAGE, 6):
                # page down: move by visible page size
                maxy, maxx = self.stdscr.getmaxyx()
                step = max(1, maxy - 2 - first_item_line)
                self.cursor = min(items_len - 1, self.cursor + step) if items_len else 0
            elif ch in (curses.KEY_PPAGE, 2):
                # page up: move by visible page size
                maxy, maxx = self.stdscr.getmaxyx()
                step = max(1, maxy - 2 - first_item_line)
                self.cursor = max(0, self.cursor - step)
            elif ch == curses.KEY_END or ch == ord('G'):
                # jump to last job and make it visible
                if items_len:
                    self.cursor = items_len - 1
                    maxy, maxx = self.stdscr.getmaxyx()
                    avail = (maxy - 2) - first_item_line
                    self.top = max(0, items_len - avail)
            elif ch in (curses.KEY_HOME, ord('0')):
                self.cursor = 0
            elif ch == ord('p'):
                # show job names in console and wait for key
                self.show_names_console()
            elif ch == ord('/'):
                self.filtered_jobs = None
                self.text_filter = self.prompt("Search text (regexp): ")
                self.text_re = None
                self.text_neg = False
                # compile regex
                # support negation prefix: '!pattern' means exclude matches
                if self.text_filter.startswith('!'):
                    self.text_neg = True
                    expr = self.text_filter[1:]
                else:
                    expr = self.text_filter
                try:
                    self.text_re = re.compile(expr, re.IGNORECASE)
                except re.error:
                    self.text_filter = ""
                self.cursor = 0
                self.top = 0
                
            elif ch == ord('n'):
                self.filtered_jobs = None
                self.name_filter = self.prompt("Name filter (regexp): ")
                self.name_neg = False
                self.name_re = None
                if self.name_filter:
                    # support negation prefix: '!pattern' means exclude matching names
                    if self.name_filter.startswith('!'):
                        self.name_neg = True
                        expr = self.name_filter[1:]
                    else:
                        expr = self.name_filter
                    if expr:
                        try:
                            self.name_re = re.compile(expr, re.IGNORECASE)
                        except re.error:
                            self.name_filter = ""
                self.cursor = 0
                self.top = 0
            elif ch == ord('s'):
                self.filtered_jobs = None
                self.status_idx = (self.status_idx + 1) % len(self.statuses)
                self.cursor = 0
                self.top = 0
            elif ch == ord('r'):
                self.filtered_jobs = None
                self.statuses = ["ALL"]
                if self.summary["end"] == "--:--:--":
                    self.jobs = load_jobs(self.dirlog)
                    self.summary = parse_result(self.dirlog)
                self.name_filter = ""
                self.text_filter = ""
                self.status_idx = 0
                self.cursor = 0
                self.top = 0
            elif ch in (curses.KEY_ENTER, 10, 13):
                if items:
                    job = items[self.cursor]
                    self.view_output(job)

def launch_tui(dirlog: str) -> None:
    if not os.path.isdir(dirlog):
        raise FileNotFoundError(f"dirlog not found: {dirlog}")

    def _curses_main(stdscr):
        tui = Tui(stdscr, dirlog)
        tui.loop()

    curses.wrapper(_curses_main)
