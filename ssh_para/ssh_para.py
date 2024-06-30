#!/usr/bin/env python
"""
    ssh-para.py parallel ssh commands
    Author: Franck Jouvanceau
"""
import os
import sys
import signal
import threading
import queue
import re
import curses
from re import sub, escape
from socket import gethostbyname_ex
from shlex import quote
from time import time, strftime, sleep
from datetime import timedelta, datetime
from subprocess import Popen, DEVNULL
from argparse import ArgumentParser
from dataclasses import dataclass
from copy import deepcopy
from colorama import Fore, Style, init

os.environ["TERM"] = "xterm-256color"

SYMBOL_END = os.environ.get("SSHP_SYM_BEG") or "\ue0b4"  # 
SYMBOL_BEGIN = os.environ.get("SSHP_SYM_END") or "\ue0b6"  # 
SYMBOL_PROG = os.environ.get("SSHP_SYM_PROG") or "\u25a0"  # ■
SYMBOL_RES = os.environ.get("SSHP_SYM_RES") or "\u25b6"  # ▶
DNS_DOMAINS = os.environ.get("SSHP_DOMAINS") or ""
SSH_OPTS = os.environ.get("SSHP_OPTS") or ""

jobq = queue.Queue()
runq = queue.Queue()
endq = queue.Queue()
printq = queue.Queue()
pauseq = queue.Queue()
resumeq = queue.Queue()


def parse_args():
    """argument parse"""
    if len(sys.argv) == 1:
        sys.argv.append("-h")
    parser = ArgumentParser()
    parser.add_argument(
        "-p", "--parallel", type=int, help="parallelism (default 4)", default=4
    )
    parser.add_argument(
        "-j", "--job", help="Job name added subdir to dirlog", default=""
    )
    parser.add_argument(
        "-d",
        "--dirlog",
        help="directory for ouput log files (~/.ssh-para)",
        default=os.path.expanduser("~/.ssh-para"),
    )
    host_group = parser.add_mutually_exclusive_group()
    host_group.add_argument("-f", "--hostsfile", help="hosts list file")
    host_group.add_argument("-H", "--hosts", help="hosts list", nargs="+")
    parser.add_argument("-s", "--script", help="script to execute")
    parser.add_argument("-a", "--args", nargs="+", help="script arguments")
    parser.add_argument("-t", "--timeout", type=int, help="timeout of each job")
    parser.add_argument(
        "-r", "--resolve", action="store_true", help="resolve fqdn in SSHP_DOMAINS"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="verbose display (fqdn + line for last output)",
    )
    parser.add_argument("ssh_args", nargs="*")
    return parser.parse_args()


def sigint_handler(*args):
    """exit all threads if signal"""
    try:
        curses.endwin()
    except curses.error:
        pass
    os._exit(1)


def resolve_host(host):
    """try get fqdn from DNS"""
    try:
        res = gethostbyname_ex(host)
    except OSError:
        return None
    return res[0]


def resolve_in_domains(host, domains):
    """try get fqdn from short hostname in domains"""
    fqdn = resolve_host(host)
    if fqdn:
        return fqdn
    for domain in domains:
        fqdn = resolve_host(f"{host}.{domain}")
        if fqdn:
            return fqdn
    return host


def resolve_hosts(hosts, domains):
    """try resolve hosts to get fqdn"""
    return [resolve_in_domains(host, domains) for host in hosts]


def addstr(stdscr, *args, **kwargs):
    """curses addstr w/o exception"""
    try:
        stdscr.addstr(*args, **kwargs)
    except (curses.error, ValueError):
        pass


def addstrc(stdscr, *args, **kwargs):
    """curses addstr and clear eol"""
    addstr(stdscr, *args, **kwargs)
    stdscr.clrtoeol()


def emptyq(q):
    """get all queue elements"""
    while True:
        try:
            q.get(block=False)
        except queue.Empty:
            break


def fillq(q, nb, value=True):
    """fill queue with nb value"""
    for _ in range(nb):
        q.put(value)


def tdelta(*args, **kwargs):
    """timedelta without microseconds"""
    return str(timedelta(*args, **kwargs)).split(".", maxsplit=1)[0]


def print_tee(*args, file=None, color="", **kwargs):
    """print stdout + file"""
    print(" ".join([color] + list(args)), file=sys.stderr, **kwargs)
    if file:
        print(*args, file=file, **kwargs)


def decode_line(line):
    """try decode line exception on binary"""
    try:
        return line.decode()
    except UnicodeDecodeError:
        return ""


def last_line(fd, maxline=1000):
    """last non empty line of file"""
    line = "\n"
    fd.seek(0, os.SEEK_END)
    size = 0
    while line == "\n" and size < maxline:
        try:  # catch if file empty / only empty lines
            while fd.read(1) != b"\n":
                fd.seek(-2, os.SEEK_CUR)
                size += 1
        except OSError:
            fd.seek(0)
            line = decode_line(fd.readline())
            break
        line = decode_line(fd.readline())
        fd.seek(-4, os.SEEK_CUR)
    return line.strip() + "\n"


def short_host(host):
    """remove dns domain from fqdn"""
    return re.sub(r"\..*", "", host)


class Segment:
    """display of colored powerline style"""

    def __init__(
        self,
        stdscr,
        nbsegments,
        bg=None,
        fg=None,
        style=None,
        seg1=True,
    ):
        """curses inits"""
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
        bg[nbsegments] = curses.COLOR_BLACK
        self.st = style or ["NORMAL"] * nbsegments
        self.seg1 = seg1
        curses.init_pair(1, bg[0], curses.COLOR_BLACK)
        for i in range(0, nbsegments):
            curses.init_pair(i * 2 + 2, fg[i], bg[i])
            curses.init_pair(i * 2 + 3, bg[i], bg[i + 1])

    def set_segments(self, x, y, segments):
        """display powerline"""
        addstr(self.stdscr, y, x, SYMBOL_BEGIN, curses.color_pair(1))
        for i, segment in enumerate(segments):
            addstr(self.stdscr, f" {segment} ", curses.color_pair(i * 2 + 2))
            addstr(self.stdscr, SYMBOL_END, curses.color_pair(i * 2 + 3))
        self.stdscr.clrtoeol()


@dataclass
class JobStatus:
    """handle job statuses"""

    status: str = "IDLE"
    start: str = ""
    host: str = ""
    duration: int = 0
    pid: int = -1
    exit: int | None = None
    logfile: str = ""
    log: str = ""
    thread_id: int = -1
    fdlog: int = 0


class JobPrint(threading.Thread):
    """
    Thread to display jobs statuses of JobRun threads
    """

    status_color = {
        "RUNNING": 100,
        "SUCCESS": 102,
        "FAILED": 104,
        "ABORTED": 104,
        "KILLED": 104,
        "TIMEOUT": 104,
        "IDLE": 106,
    }
    COLOR_GAUGE = 108
    COLOR_HOST = 110

    def __init__(
        self,
        command,
        nbthreads,
        nbjobs,
        dirlog,
        timeout=0,
        verbose=False,
        maxhostlen=15,
    ):
        """init properties / thread"""
        super().__init__()
        self.th_status = [JobStatus() for i in range(nbthreads)]
        self.command = " ".join(command)
        self.job_status = []
        self.nbthreads = nbthreads
        self.nbfailed = 0
        self.nbjobs = nbjobs
        self.dirlog = dirlog
        self.aborted = []
        self.startsec = time()
        self.stdscr = None
        self.paused = False
        self.timeout = timeout
        self.verbose = verbose
        self.maxhostlen = maxhostlen
        home = os.path.expanduser("~/")
        self.pdirlog = sub(rf"^{escape(home)}", "~/", self.dirlog)
        if sys.stdout.isatty():
            self.init_curses()
        super().__init__()

    def init_curses(self):
        """curses window init"""
        self.stdscr = curses.initscr()
        # self.stdscr.scrollok(True)
        curses.noecho()
        curses.curs_set(0)
        curses.start_color()
        self.segment = Segment(self.stdscr, 5)
        curses.init_pair(
            self.status_color["RUNNING"], curses.COLOR_WHITE, curses.COLOR_BLUE
        )
        curses.init_pair(
            self.status_color["RUNNING"] + 1, curses.COLOR_BLUE, curses.COLOR_BLACK
        )
        curses.init_pair(
            self.status_color["SUCCESS"], curses.COLOR_WHITE, curses.COLOR_GREEN
        )
        curses.init_pair(
            self.status_color["SUCCESS"] + 1, curses.COLOR_GREEN, curses.COLOR_BLACK
        )
        curses.init_pair(
            self.status_color["FAILED"], curses.COLOR_WHITE, curses.COLOR_RED
        )
        curses.init_pair(
            self.status_color["FAILED"] + 1, curses.COLOR_RED, curses.COLOR_BLACK
        )
        curses.init_pair(self.status_color["IDLE"], curses.COLOR_WHITE, 8)
        curses.init_pair(self.status_color["IDLE"] + 1, 8, curses.COLOR_BLACK)
        curses.init_pair(self.COLOR_GAUGE, 8, curses.COLOR_BLUE)
        curses.init_pair(self.COLOR_HOST, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    def join(self, *args):
        """returns nb failed"""
        super().join(*args)
        return self.nbfailed > 0

    def run(self):
        """get threads status change"""
        jobsdur = 0
        nbsshjobs = 0
        while True:
            try:
                jstatus: JobStatus = printq.get(timeout=0.1)
            except queue.Empty:
                jstatus = None
            th_id = None
            if jstatus:
                if not jstatus.fdlog:  # start RUNNING
                    jstatus.fdlog = open(jstatus.logfile, "rb")
                jstatus.log = last_line(jstatus.fdlog)
                if jstatus.exit is not None:  # FINISHED
                    jstatus.fdlog.close()
                    jstatus.fdlog = 0
                    self.job_status.append(jstatus)
                    nbsshjobs += 1
                    jobsdur += jstatus.duration
                if jstatus.status in ["FAILED", "KILLED", "TIMEOUT"]:
                    self.nbfailed += 1
                    if jstatus.exit == 255:
                        nbsshjobs -= 1
                        jobsdur -= jstatus.duration
                self.th_status[jstatus.thread_id] = jstatus
                if not self.stdscr:
                    print(
                        f"{strftime('%X')}: {jstatus.status} {int(runq.qsize())}: {jstatus.host}"
                    )
            total_dur = tdelta(seconds=round(time() - self.startsec))
            if self.stdscr:
                self.display_curses(th_id, total_dur, jobsdur, nbsshjobs)
            else:
                self.check_timeouts()
            if len(self.job_status) == self.nbjobs:
                break
        self.resume()
        end = strftime("%X")
        if self.stdscr:
            addstrc(self.stdscr, curses.LINES - 1, 0, "All jobs finished")
            self.stdscr.refresh()
            self.stdscr.getch()
            curses.endwin()
            curses.echo()
            curses.curs_set(1)
        self.print_summary(end, total_dur)

    def check_timeout(self, th_id, duration):
        """kill ssh if duration exceeds timeout"""
        if not self.timeout:
            return
        if duration > self.timeout:
            self.kill("TIMEOUT", th_id)

    def check_timeouts(self):
        """check threads timemout"""
        for i, jstatus in enumerate(self.th_status):
            if jstatus.status == "RUNNING":
                duration = time() - jstatus.start
                self.check_timeout(i, duration)

    def print_status(self, status, duration=0, avgjobdur=0):
        """print thread status"""
        color = self.status_color[status]
        addstr(self.stdscr, SYMBOL_BEGIN, curses.color_pair(color + 1))
        if status == "RUNNING" and avgjobdur:
            pten = min(int(round(duration / avgjobdur * 10, 0)), 10)
            addstr(
                self.stdscr,
                SYMBOL_PROG * pten + " " * (10 - pten),
                curses.color_pair(self.COLOR_GAUGE),
            )  # ▶
        else:
            addstr(self.stdscr, f" {status:8} ", curses.color_pair(color))
        addstr(self.stdscr, SYMBOL_END, curses.color_pair(color + 1))
        addstr(self.stdscr, f" {tdelta(seconds=round(duration))}")

    def print_job(self, line_num, jstatus, duration, avgjobdur):
        """print host runnin on thread and last out line"""
        th_id = str(jstatus.thread_id).zfill(2)
        addstr(self.stdscr, line_num, 0, f" {th_id} ")
        self.print_status(jstatus.status, duration, avgjobdur)
        addstr(self.stdscr, f" {str(jstatus.pid):>7} ")
        if self.verbose:
            addstrc(self.stdscr, jstatus.host, curses.color_pair(self.COLOR_HOST))
            addstrc(self.stdscr, line_num + 1, 0, "     " + jstatus.log)
        else:
            addstr(
                self.stdscr,
                f"{short_host(jstatus.host):{self.maxhostlen}} {SYMBOL_RES} ",
                curses.color_pair(self.COLOR_HOST),
            )
            addstrc(self.stdscr, jstatus.log)

    def display_curses(self, status_id, total_dur, jobsdur, nbsshjobs):
        """display threads statuses"""
        nbend = endq.qsize()
        last_start = 0
        avgjobdur = 0
        curses.update_lines_cols()
        self.get_key()
        if nbsshjobs:
            avgjobdur = jobsdur / nbsshjobs
        inter = self.verbose + 1
        line_num = 3
        nbrun = 0
        for jstatus in self.th_status:
            if jstatus.fdlog and jstatus.thread_id != status_id:
                jstatus.log = last_line(jstatus.fdlog)
            if jstatus.status == "RUNNING":
                duration = time() - jstatus.start
                self.check_timeout(jstatus.thread_id, duration)
                last_start = max(last_start, jstatus.start)
                nbrun += 1
                if curses.LINES > line_num:
                    self.print_job(line_num, jstatus, duration, avgjobdur)
                    line_num += inter
            else:
                duration = jstatus.duration
        addstrc(self.stdscr, line_num, 0, "")
        if nbsshjobs:
            last_dur = time() - last_start
            nbjobsq = max(min(self.nbthreads, nbrun), 1)
            estimated = tdelta(
                seconds=round(
                    max(avgjobdur * (self.nbjobs - nbend) / nbjobsq - last_dur, 0)
                )
            )
        else:
            estimated = ".:..:.."
        jobslabel = "paused" if self.paused else "pending"
        self.segment.set_segments(
            0,
            0,
            [
                f"running: {nbrun} {jobslabel}: {self.nbjobs-nbend-nbrun}",
                f"done: {nbend}/{self.nbjobs}",
                f"failed: {self.nbfailed}",
                f"duration: {total_dur}",
                f"ETA: {estimated}",
            ],
        )
        addstrc(self.stdscr, 1, 0, f" Dirlog: {self.pdirlog} Command: {self.command}")
        addstrc(self.stdscr, 2, 0, "")
        self.print_finished(line_num + (nbrun > 0))
        if self.paused:
            addstrc(self.stdscr, curses.LINES - 1, 0, "[a]bort [k]ill [r]esume")
        else:
            addstrc(self.stdscr, curses.LINES - 1, 0, "[a]bort [k]ill [p]ause")
        self.stdscr.refresh()

    def get_key(self):
        """manage interactive actions"""
        self.stdscr.nodelay(True)
        ch = self.stdscr.getch()
        self.stdscr.nodelay(False)
        # addstrc(self.stdscr, curses.LINES-1, 0, "===> "+str(ch))
        if ch == 97:  # a => abort (cancel)
            self.abort_jobs()
        if ch == 107:  # k kill
            self.kill()
        if ch == 112 and not self.paused:  # p pause
            self.pause()
        if ch == 114 and self.paused:  # r resume
            self.resume()

    def kill(self, status="KILLED", th_kill=None):
        """interactive kill pid of ssh thread"""
        if th_kill is None:
            curses.echo()
            addstrc(self.stdscr, curses.LINES - 1, 0, "kill job in thread: ")
            try:
                th_kill = int(self.stdscr.getstr())
            except ValueError:
                return
            finally:
                curses.noecho()
        try:
            os.kill(self.th_status[th_kill].pid, 15)
            sleep(0.1)
            self.th_status[th_kill].status = status
        except ProcessLookupError:
            pass

    def pause(self):
        """pause JobRun threads"""
        if not self.paused:
            emptyq(resumeq)
            fillq(pauseq, self.nbthreads)
            self.paused = True

    def resume(self):
        """resume JobRun threads"""
        if self.paused:
            emptyq(pauseq)
            fillq(resumeq, self.nbthreads)
            self.paused = False

    def print_finished(self, line_num):
        """display finished jobs"""
        addstr(self.stdscr, curses.LINES - 1, 0, "")
        inter = self.verbose + 1
        for jstatus in self.job_status[::-1]:
            if curses.LINES < line_num + 2:
                break
            addstr(self.stdscr, line_num, 0, "")
            self.print_status(jstatus.status, jstatus.duration)
            addstr(self.stdscr, f" exit:{str(jstatus.exit):>3} ")
            if self.verbose:
                addstrc(self.stdscr, jstatus.host, curses.color_pair(self.COLOR_HOST))
                addstrc(self.stdscr, line_num + 1, 0, "     " + jstatus.log)
            else:
                addstr(
                    self.stdscr,
                    f"{short_host(jstatus.host):{self.maxhostlen}} {SYMBOL_RES} ",
                    curses.color_pair(self.COLOR_HOST),
                )
                addstrc(self.stdscr, jstatus.log)
            line_num += inter
        self.stdscr.clrtobot()

    def abort_jobs(self):
        """aborts remaining jobs"""
        addstrc(self.stdscr, curses.LINES - 1, 0, "Cancel remaining jobs...")
        self.stdscr.refresh()
        while True:
            try:
                job = jobq.get(block=False)
                job.status.status = "ABORTED"
                job.status.exit = 256
                self.job_status.append(job.status)
                runq.put(True)
                endq.put(True)
            except queue.Empty:
                break
            self.aborted.append(job.host)
        self.resume()

    def print_summary(self, end, total_dur):
        """print/log summary of jobs"""
        global_log = open(f"{self.dirlog}/ssh-para.log", "w", encoding="UTF-8")
        if self.aborted:
            print_tee(
                "Cancelled hosts:", file=global_log, color=Style.BRIGHT + Fore.RED
            )
            for host in self.aborted:
                print_tee(host, file=global_log)
                self.nbjobs -= 1
        print_tee("", file=global_log)
        for jstatus in self.job_status:
            if jstatus.exit != 0:
                color = Style.BRIGHT + Fore.RED
            else:
                color = Style.BRIGHT + Fore.GREEN
            print_tee(f"{jstatus.status:8}:", color=color, file=global_log, end="")
            print_tee(jstatus.host, color=Fore.YELLOW, file=global_log, end="")
            print_tee(
                f"exit: {jstatus.exit}",
                f"dur: {tdelta(seconds=jstatus.duration)}",
                f"{self.pdirlog}/{jstatus.host}.out",
                file=global_log,
            )
            print_tee(" ", jstatus.log, file=global_log)
        print_tee("command:", self.command, file=global_log)
        print_tee("log directory:", self.pdirlog, file=global_log)
        print_tee(
            f"{self.nbjobs} jobs run : Start: {strftime('%X', datetime.fromtimestamp(self.startsec).timetuple())}",
            f"End: {end} Duration: {total_dur}",
            file=global_log,
        )
        if self.nbfailed == 0:
            print_tee("All Jobs with exit code 0", file=global_log)
        else:
            print_tee(
                f"WARNING : {str(self.nbfailed)} Job(s) with exit code != 0",
                file=global_log,
                color=Style.BRIGHT + Fore.RED,
            )
        global_log.close()


class Job:
    """manage job execution"""

    def __init__(self, host, command):
        """job to run on host init"""
        self.host = host
        self.command = command
        self.status = JobStatus(host=host)

    def exec(self, th_id, dirlog):
        """run command on host using ssh"""
        runq.put(th_id)
        self.status.start = time()
        self.status.thread_id = th_id
        jobcmd = (
            ["ssh", self.host, "-T", "-n", "-o", "BatchMode=yes"]
            + SSH_OPTS.split()
            + self.command
        )
        self.status.logfile = f"{dirlog}/{self.host}.out"
        if dirlog:
            fdout = open(self.status.logfile, "w", encoding="UTF-8", buffering=1)
        else:
            fdout = sys.stdout
        p = Popen(
            jobcmd,
            bufsize=0,
            encoding="UTF-8",
            stdout=fdout,
            stderr=fdout,
            stdin=DEVNULL,
            close_fds=True,
        )
        self.status.status = "RUNNING"
        self.status.pid = p.pid
        printq.put(deepcopy(self.status))
        p.wait()
        fdout.close()
        endq.put(th_id)
        self.status.exit = p.returncode
        self.status.duration = time() - self.status.start
        self.status.status = "SUCCESS" if self.status.exit == 0 else "FAILED"
        printq.put(self.status)
        with open(f"{dirlog}/{self.host}.status", "w", encoding="UTF-8") as fstatus:
            print(
                "EXIT CODE:",
                self.status.exit,
                self.status.status,
                self.status.duration,
                file=fstatus,
            )


class JobRun(threading.Thread):
    """
    Threads launching jobs from rung in parallel
    """

    def __init__(self, thread_id, dirlog=""):
        """constructor"""
        self.thread_id = thread_id
        self.dirlog = dirlog
        super().__init__()

    def run(self):
        """schedule Jobs / pause / resume"""
        while True:
            try:
                if pauseq.get(block=False):
                    resumeq.get()
            except queue.Empty:
                pass
            try:
                job: Job = jobq.get(block=False)
            except queue.Empty:
                break
            job.exec(self.thread_id, self.dirlog)


def script_command(script, args):
    """build ssh command to transfer and execute script with args"""
    try:
        with open(script, "r", encoding="UTF-8") as fd:
            scriptstr = fd.read()
    except OSError:
        print(f"ERROR: ssh-para: Cannot open {script}", file=sys.stderr)
        sys.exit(1)
    if args:
        argstr = " ".join([quote(i) for i in args])
    else:
        argstr = ""
    command = f"""
cat - >/tmp/.ssh-para.$$ <<'__ssh_para_EOF'
{scriptstr}
__ssh_para_EOF
[ $? = 0 ] || {{
    echo "ERROR: ssh-para: Cannot create /tmp/.ssh-para.$$" >&2
    rm -f /tmp/.ssh-para.$$
    exit 255
}}
chmod u+x /tmp/.ssh-para.$$
/tmp/.ssh-para.$$ {argstr}
e=$?
rm /tmp/.ssh-para.$$
exit $e
"""
    return command


def get_hosts(hostsfile, hosts):
    """returns hosts list from args host or reading hostfile"""
    if hosts:
        return hosts
    if not hostsfile:
        print("ERROR: ssh-para: No hosts definition", file=sys.stderr)
        sys.exit(1)
    try:
        with open(hostsfile, "r", encoding="UTF-8") as fhosts:
            hosts = fhosts.read().splitlines()
    except OSError:
        print(f"ERROR: ssh-para: Cannot open {hostsfile}", file=sys.stderr)
        sys.exit(1)
    return hosts


def main():
    """argument read / read hosts file / prepare commands / launch jobs"""
    init(autoreset=True)
    args = parse_args()
    dirlog = args.dirlog
    if args.job:
        dirlog += f"/{args.job}"
    dirlog += "/" + str(int(time()))
    if not os.path.isdir(dirlog):
        os.makedirs(dirlog)
    latest = f"{args.dirlog}/latest"
    if os.path.exists(latest):
        os.unlink(latest)
    try:
        os.symlink(dirlog, latest)
    except OSError:
        pass
    if args.script:
        args.ssh_args.append(script_command(args.script, args.args))
        command = [args.script]
        if args.args:
            command += args.args
    else:
        command = args.ssh_args
    hosts = get_hosts(args.hostsfile, args.hosts)
    max_len = 0
    for host in hosts:
        max_len = max(max_len, len(short_host(host)))
    if args.resolve:
        print("Notice: ssh-para: Resolving hosts...", file=sys.stderr)
        hosts = resolve_hosts(hosts, DNS_DOMAINS.split())
        print("Notice: ssh-para: Resolve done", file=sys.stderr)
    if not args.ssh_args:
        print("ERROR: ssh-para: No ssh command supplied", file=sys.stderr)
        sys.exit(1)
    for host in hosts:
        jobq.put(Job(host=host, command=args.ssh_args))
    parallel = min(len(hosts), args.parallel)
    signal.signal(signal.SIGINT, sigint_handler)
    p = JobPrint(
        command, parallel, len(hosts), dirlog, args.timeout, args.verbose, max_len
    )
    p.start()
    for i in range(parallel):
        t = JobRun(i, dirlog=dirlog)
        t.start()
        sleep(0.3)
    for i in threading.enumerate():
        if i != threading.current_thread() and i != p:
            i.join()
    exit_code = p.join()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
