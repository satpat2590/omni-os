"""omnikit — code shared across Omni OS domains, owned here and imported by each.

Modules:
    jev          — the one Jev (TypeSafe System One) decisions client; domains keep thin shims
    jev_decider  — ``Decision`` / ``JevDecider`` distribution primitives over a ``JevClient``

Installed into each runtime by ``~/omni/lib/install.sh`` (a ``.pth`` pointing at ``src``).
"""

__version__ = "0.1.0"
