# ssh-para
Parallel SSH jobs manager CLI (alternative to parallel-ssh)
* Launch parallel ssh jobs/scripts on remote hosts, with interactive display of the running commands outputs
* Keep all output in log files
* Interactive pause/resume/abort jobs, kill stuck ssh connection interactively.

![ssh-para](https://github.com/joknarf/ssh-para/assets/10117818/f793e07e-b31e-4afe-befa-b38f19552eff)


# installation
```shell
pip install ssh-para
```
# usage
```
ssh-para -h
```
```
usage: ssh-para [-h] [-p PARALLEL] [-j JOB] [-d DIRLOG] [-f HOSTSFILE | -H HOSTS [HOSTS ...]]
                [-s SCRIPT] [-a ARGS [ARGS ...]] [-t TIMEOUT]
                [ssh_args ...]

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
  -s SCRIPT, --script SCRIPT
                        script to execute
  -a ARGS [ARGS ...], --args ARGS [ARGS ...]
                        script arguments
  -t TIMEOUT, --timeout TIMEOUT
                        timeout of each jobs
```
During run, use :
* k: to kill ssh command held by a thread (but remote command can still be running on remote host)
* p: pause all remaining jobs to be scheduled
* r: resume scheduling of jobs
* a: abort all remaining jobs
* ctrl-c: stop all/exit (but remote commands launched by ssh can still be running on remote servers)

# Example

Patch redhat family hosts:
```
ssh-para -p 20 -f hostlist.txt -- 'sudo yum update -y;sudo shutdown -r +1'
```
Use specific ssh options / config (everything after `--` will be passed to ssh command as is):
```
ssh-para -p 20 -H host1 host2 -- -F ~/.ssh/myconfig echo connect ok
```
Launch local script with argument on remote hosts:
```
ssh-para -p 20 -f hosts.txt -s ./myscript -a status
```
