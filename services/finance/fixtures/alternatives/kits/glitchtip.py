"""FIXTURE kit for GlitchTip: accepts Sentry-SDK-shaped events, groups issues, alerts; tracing is limited."""
import hashlib


class Server:
    def __init__(self):
        self.issues, self.alerts = {}, []

    def ingest(self, event):
        if "exception" not in event or "platform" not in event:
            raise ValueError("not a Sentry event")
        frame = event["exception"]["values"][0]
        key = hashlib.sha1(f'{frame["type"]}:{frame["stacktrace"]["frames"][-1]["function"]}'.encode()).hexdigest()
        new = key not in self.issues
        self.issues.setdefault(key, []).append(event)
        if new:
            self.alerts.append(key)
        return key

    def trace(self, transaction):
        raise NotImplementedError("performance tracing is limited in this candidate")


def start():
    return Server()
