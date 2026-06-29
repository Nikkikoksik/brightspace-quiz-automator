_DEFAULT_SENTRY_DSN = (
    "https://b178c330abfc081169e6395ae85da7db"
    "@o4511530722459648.ingest.de.sentry.io/4511530734780496"
)


def _init_sentry(dsn: str = ""):
    try:
        import sentry_sdk
        from gui.constants import VERSION
        resolved = dsn or _DEFAULT_SENTRY_DSN
        if resolved:
            sentry_sdk.init(dsn=resolved, traces_sample_rate=0, release=VERSION)
    except Exception:
        pass


def _sentry_capture(e: Exception):
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
    except Exception:
        pass


def _sentry_context(step: str, course: str = ""):
    try:
        import sentry_sdk
        sentry_sdk.set_tag("step", step)
        if course:
            sentry_sdk.set_tag("course", course)
    except Exception:
        pass
