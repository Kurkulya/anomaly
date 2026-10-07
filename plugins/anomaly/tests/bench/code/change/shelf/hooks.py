"""Hooks that other code registers to hear about catalogue events."""


def run_hooks(hooks, event):
    """Call every hook with `event`; one failing hook never stops the others.

    Returns the (hook, error) pairs of the hooks that raised."""
    failures = []
    for hook in hooks:
        try:
            hook(event)
        except Exception as error:  # a hook is third-party code and may raise anything; the failure is returned
            failures.append((hook, error))
    return failures
