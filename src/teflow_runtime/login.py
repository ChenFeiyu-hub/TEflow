"""Read logind properties without conflating absent evidence with a false value."""
import os

from .systemd import call


def parse_login(result):
    props = {}
    duplicates = set()
    for row in result.get("stdout", "").splitlines():
        if "=" in row:
            key, value = row.split("=", 1)
            if key in props:
                duplicates.add(key)
            props[key] = value
    valid = (result.get("returncode") == 0 and props.get("Linger") in ("yes", "no")
             and "Sessions" in props and not duplicates.intersection(("Linger", "Sessions")))
    return dict(status="LOGIN_STATE_READ" if valid else "LOGIN_STATE_UNAVAILABLE",
                linger=props.get("Linger") if valid else None,
                session_count=len(props["Sessions"].split()) if valid else None,
                sessions=props["Sessions"].split() if valid else None, command=result)


def login_state(detailed=False):
    # loginctl v252 accepts repeated properties, not a comma-separated list.
    # Keep keys, including an explicit empty Sessions=, to distinguish zero from missing.
    state = parse_login(call(["loginctl", "show-user", str(os.getuid()), "-p", "Linger", "-p", "Sessions",
                             "--all", "--no-pager"], timeout=2))
    if not detailed: return state
    sessions = []
    for sid in state['sessions'] or []:
        reply = call(['loginctl','show-session',sid,'-p','Id','-p','State','-p','Active',
                      '-p','Service','-p','Leader','-p','TTY','--all','--no-pager'],timeout=2)
        props = dict(row.split('=',1) for row in reply.get('stdout','').splitlines() if '=' in row)
        known = reply.get('returncode')==0 and props.get('Id')==sid and props.get('State') in ('active','online','closing')
        sessions.append(dict(id=sid,known=known,properties=props,command=reply))
    known = state['sessions'] is not None and all(s['known'] for s in sessions)
    state.update(session_details=sessions,
        active_or_online_sessions=sum(s['properties']['State'] in ('active','online') for s in sessions) if known else None,
        closing_sessions=sum(s['properties']['State']=='closing' for s in sessions) if known else None,
        note='State is the lifecycle state; Active=yes does not turn a closing session into a live login. Strict B3 still requires zero registered sessions; this query does not change its verdict.')
    return state
