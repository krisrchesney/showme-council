"""Source registry. A new city is one entry here plus its adapter module (TASKS.md T-4, T-6)."""

from pipeline.sources.legistar import FixtureTransport, LegistarSource


def get_source(name, fixture=False):
    if name == "kansascity":
        t = FixtureTransport("kansascity") if fixture else None
        return LegistarSource("kansascity", prefix="kc", transport=t)
    raise KeyError(f"unknown source {name!r}; known: kansascity")
