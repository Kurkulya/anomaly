"""The weekly nudge: one line for the user, in the first session of an ISO week, when something needs them.

The plugin's SessionStart hook (hooks/hooks.json, startup only) runs `anomaly nudge`. It says
something when an open or reopened problem has a score of NUDGE_MIN_SCORE or more, or an
experiment is due (trends.experiment_due, the same rule as the digest), and otherwise prints
nothing. No model is involved. The question is asked of a digest Context, so the anomalies, the
metrics rows and the session kinds are read only when the week is new.

The week is marked in NUDGE_MARKER_FILE under the data folder (never in home) the first time the
command runs in that ISO week, whether or not it had anything to say, so the question is asked
once a week. A marker that cannot be read counts as not set. The week is marked before the
anomalies are read, so a file that cannot be read is reported once a week, not at every startup.

Output: a single JSON object `{"systemMessage": "<line>"}`. For SessionStart, Claude Code adds
plain stdout to the model's context, which would cost tokens; `systemMessage` is shown to the user
only.
"""
import json

from . import digest, paths, records, trends
from .constants import NUDGE_MARKER_FILE, NUDGE_MIN_SCORE
from .files import write_lines
from .flags import plural


def iso_week(day):
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def claim_week(today, marker):
    """True the first time it is called in an ISO week, and marks the week in `marker` (see the
    module doc); False when the week is already marked."""
    week = iso_week(today)
    try:
        if marker.read_text(encoding='utf-8').strip() == week:
            return False
    except (OSError, ValueError):
        pass
    write_lines(marker, [week])
    return True


def summary_line(context):
    """The line for the context's anomalies, or None when nothing needs the user."""
    hot = [a for a in records.ranked(context.anomalies) if a.kind == 'problem' and a.score >= NUDGE_MIN_SCORE]
    due = trends.due_experiments(context)
    parts = []
    if hot:
        parts.append(f'{plural(len(hot), "open problem")} with score >= {NUDGE_MIN_SCORE} '
                     f'(top: {hot[0].signature} ({hot[0].score}))')
    if due:
        parts.append(f'{plural(len(due), "experiment")} due')
    return f'anomaly: {"; ".join(parts)}. Say "calibrate" to review.' if parts else None


def nudge_line(context, marker):
    """The line to show, or None. Marks the week in `marker` as a side effect (see the module doc)."""
    return summary_line(context) if claim_week(context.today, marker) else None


# ---------- the nudge subcommand ----------

def register(commands, common):
    command = commands.add_parser('nudge', parents=[common, digest.folder_options()],
                                  help='print the once-a-week reminder as a user-only message (for the hook)')
    command.set_defaults(handler=run_nudge)


def run_nudge(args, environ):
    home = paths.resolve_home(args.home, environ)
    data = paths.resolve_data(args.data, environ, home)
    line = nudge_line(digest.context_from_args(args, environ, data=data), data / NUDGE_MARKER_FILE)
    if line:
        print(json.dumps({'systemMessage': line}))
    return 0
