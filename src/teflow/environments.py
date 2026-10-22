"""Environment prefixes are independent of the tool's interpreter and arguments."""
from .common import WorkflowError


def environment_command(c, name):
    argv = c["tools"][name]["command"]
    if "-p" not in argv or argv.index("-p") + 1 >= len(argv):
        raise WorkflowError(name + " requires the documented micromamba -p environment prefix")
    return argv[:argv.index("-p") + 2]
