[![Pypi version](https://img.shields.io/pypi/v/ssh-para.svg)](https://pypi.org/project/ssh-para/)
![example](https://github.com/joknarf/ssh-para/actions/workflows/python-publish.yml/badge.svg)
[![Licence](https://img.shields.io/badge/licence-MIT-blue.svg)](https://shields.io/)
[![](https://pepy.tech/badge/ssh-para)](https://pepy.tech/project/ssh-para)
[![Python versions](https://img.shields.io/badge/python-3.6+-blue.svg)](https://shields.io/)



# ssh-para
Parallel SSH jobs manager CLI (alternative to parallel-ssh)
* POSIX/Linux/MacOS/Windows compatible (with openssh client installed)
* Launch parallel ssh jobs/scripts on remote hosts, with interactive display of the running commands outputs
* Keep all output in log files
* Interactive pause/resume/abort jobs, kill stuck ssh connection interactively.

![ssh-para3](https://github.com/joknarf/ssh-para/assets/10117818/aef84de2-d15c-44f6-b6ff-74dc5f6f7b08)


# installation
```shell
pip install ssh-para
```
By default, `ssh-para` uses Nerd Fonts glyphs, modern terminals can now render the glyphs without installing specific font (the symbols can be overridden with SSHP_SYM_* environment variables, see below)

# usage
```
ssh-para -h
```
```
usage: ssh-para [-h] [-p PARALLEL] [-j JOB] [-d DIRLOG] [-f HOSTSFILE | -H HOSTS [HOSTS ...]] 
                [-D DELAY] [-s SCRIPT] [-a ARGS [ARGS ...]] [-t TIMEOUT] [-r] [-v] -- [ssh_args ...]

positional arguments:
  ssh_args

options:
  -h, --help            show this help message and exit
  -p PARALLEL, --parallel PARALLEL
                        parallelism (default 4)
  -j JOB, --job JOB     Job name added subdir to dirlog
  -d DIRLOG, --dirlog DIRLOG
                        directory for ouput log files (~/.ssh-para)
  -f HOSTSFILE, --hostsfile HOSTSFILE
                        hosts list file
  -H HOSTS [HOSTS ...], --hosts HOSTS [HOSTS ...]
                        hosts list
  -D DELAY, --delay DELAY
                        initial delay in seconds between ssh commands (default=0.3s)
  -s SCRIPT, --script SCRIPT
                        script to execute
  -a ARGS [ARGS ...], --args ARGS [ARGS ...]
                        script arguments
  -t TIMEOUT, --timeout TIMEOUT
                        timeout of each job
  -r, --resolve         resolve fqdn in SSHP_DOMAINS
  -v, --verbose         verbose display (fqdn + line for last output)```
During run, use :
* k: to kill ssh command held by a thread (but remote command can still be running on remote host)
* p: pause all remaining jobs to be scheduled
* r: resume scheduling of jobs
* a: abort all remaining jobs
* ctrl-c: stop all/exit (but remote commands launched by ssh can still be running on remote servers)

Environment variables:
* SSHP_OPTS: ssh default options (Eg: "-F /home/user/.ssh/myconfig")
* SSHP_DOMAINS: dns domains to search when short hostname given (with -r/--resolve option)
* SSHP_SYM_BEG: Symbol character for begin decorative (default: "\ue0b4")
* SSHP_SYM_END: Symbol character for end decorative (default: "\ue0b6")
* SSHP_SYM_PROG: Symbol character for progress bar fill (default: "\u25a0")
* SSHP_SYM_RES: Symbol character before ssh output line (default: "\u25b6")

# Example

Patch redhat family hosts:
```shell
ssh-para -p 20 -f hostlist.txt -- 'sudo yum update -y;sudo shutdown -r +1'
```
Use specific ssh options / config (everything after `--` will be passed to ssh command as is):
```shell
ssh-para -p 20 -H host1 host2 -- -F ~/.ssh/myconfig echo connect ok
```
Launch local script with argument on remote hosts:
```shell
ssh-para -p 20 -f hosts.txt -s ./myscript -a status
```
Extend limited resolv.conf search domains (try to resolve host in each domain, first resolved in the domain list is used as fqdn):
```shell
SSHP_DOMAINS="domain1.com domain2.com" ssh-para -r -H host1 host2 -- echo connect ok
```

# Tips

* if you are using ssh ProxyJump server to reach hosts, you may need to tweak the sshd MaxStartups setting on the ssh Proxy server with high parallelism
  * when ssh-para starts, a delay of 0.3 seconds is applied between threads starting ssh jobs to avoid flooding, (can be tweaked with -D <delay>)
* if you are using remote connexion to launch the ssh-para, use `screen` to launch ssh-para, as if you lose your connection, ssh-para will be still running and you can re-attach to `screen` to continue follow-up.
* Be very carefull when launching massive commands on servers... Always first test on non production.