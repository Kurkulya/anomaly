"""Command-line entry point."""
import sys

from . import admin, service


def reprioritize_command(args):
    """`reprioritize <job id> <priority>`."""
    job_id, priority = args[0], int(args[1])
    return service.set_priority(job_id, priority)


def main(argv):
    """Run the command named by the first argument."""
    commands = {'reprioritize': reprioritize_command, 'cancel': admin.cancel_command,
                'show': admin.show_command}
    return commands[argv[1]](argv[2:])


if __name__ == '__main__':
    main(sys.argv)
