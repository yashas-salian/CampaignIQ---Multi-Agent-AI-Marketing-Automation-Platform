"""Error tracking (Sentry) and LLM/graph tracing (Langfuse) for the workers.

Both are optional and free-tier friendly; each switches on only when its keys
are set, and nothing here can fail a run:
  SENTRY_DSN                                  uncaught errors + breadcrumbs
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY    one trace per run: a span per graph
  (LANGFUSE_HOST, default cloud.langfuse.com) step, a generation per LLM call
  LANGFUSE_CAPTURE_CONTENT=true               also send prompt/response text
                                              (off by default: prompts carry
                                              customers' campaign content)
Without any of them, every helper is a no-op.
"""
import atexit
import contextlib
import functools
import logging
import os
from importlib.metadata import PackageNotFoundError, version

logger = logging.getLogger("observability")

_langfuse = None
_initialised = False


def _release() -> str:
    try:
        return f"marketingos@{version('ad-campaign-agent')}"
    except PackageNotFoundError:
        return "marketingos@dev"


def init(service: str) -> None:
    """Call once at the start of a worker entrypoint."""
    global _langfuse, _initialised
    if _initialised:
        return
    _initialised = True
    environment = os.environ.get("APP_ENV", "production" if os.environ.get("GITHUB_ACTIONS") else "development")

    if os.environ.get("SENTRY_DSN"):
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=os.environ["SENTRY_DSN"],
                environment=environment,
                release=_release(),
                traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
                send_default_pii=False,
            )
            sentry_sdk.set_tag("service", service)
        except Exception as exc:
            logger.warning("Sentry disabled: %s", exc)

    if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse import Langfuse

            _langfuse = Langfuse(environment=environment, release=_release())
            atexit.register(flush)
        except Exception as exc:
            logger.warning("Langfuse disabled: %s", exc)


def flush() -> None:
    if _langfuse is not None:
        try:
            _langfuse.flush()
        except Exception:
            pass


def _capture_content() -> bool:
    return os.environ.get("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"


@contextlib.contextmanager
def span(name: str, **metadata):
    """A traced step (no-op without Langfuse). Yields an object with .update()."""
    if _langfuse is None:
        yield _Noop()
        return
    try:
        cm = _langfuse.start_as_current_observation(name=name, as_type="span", metadata=metadata or None)
        obs = cm.__enter__()
    except Exception:
        yield _Noop()
        return
    try:
        yield obs
    except BaseException as exc:
        cm.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        cm.__exit__(None, None, None)


@contextlib.contextmanager
def generation(provider: str, model: str | None, *, prompt: str, system: str | None, **metadata):
    """One LLM call. The caller reports the outcome with .done()/.failed()."""
    if _langfuse is None:
        yield _Noop()
        return
    content = _capture_content()
    try:
        cm = _langfuse.start_as_current_observation(
            name=f"llm:{provider}",
            as_type="generation",
            model=model,
            input=({"system": system, "prompt": prompt} if content else None),
            metadata={"provider": provider, **metadata},
        )
        obs = cm.__enter__()
    except Exception:
        yield _Noop()
        return
    handle = _Generation(obs, content)
    try:
        yield handle
    finally:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass


class _Noop:
    def update(self, **_):
        pass

    def done(self, *_, **__):
        pass

    def failed(self, *_, **__):
        pass


class _Generation:
    def __init__(self, obs, content: bool):
        self.obs, self.content = obs, content

    def done(self, text: str, usage) -> None:
        try:
            details = None
            if usage is not None:
                details = {
                    "input": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "output": int(getattr(usage, "completion_tokens", 0) or 0),
                }
            self.obs.update(output=text if self.content else None, usage_details=details)
        except Exception:
            pass

    def failed(self, error: str) -> None:
        try:
            self.obs.update(level="ERROR", status_message=error[:500])
        except Exception:
            pass


def traced_node(name: str, fn):
    """Wrap a LangGraph node so each step shows up as a span in the run's trace.
    A human-gate interrupt is a pause, not a failure."""

    @functools.wraps(fn)
    def wrapper(state):
        with span(f"node:{name}", campaign_id=state.get("campaign_id"), round=state.get("round_id")) as obs:
            try:
                return fn(state)
            except Exception as exc:
                if type(exc).__name__ == "GraphInterrupt":
                    obs.update(status_message="paused for a human decision")
                else:
                    obs.update(level="ERROR", status_message=f"{type(exc).__name__}: {str(exc)[:300]}")
                raise

    return wrapper
