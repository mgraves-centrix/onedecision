"""SYNTHETIC ADAPTERS.

Every module in this package is a *simulation* of a business system, backed by
the local SQLite database and seeded from `fixtures/`. None of it is a
production integration. There is no real WMS, ERP, carrier, payment processor,
or customer on the other end of any call made here, and no real company,
person, order, or serial number appears in the data.

They exist so the agent has genuine tools to call and genuine state to change,
and so the golden path can be replayed deterministically.
"""

SYNTHETIC_NOTICE = (
    "SYNTHETIC ADAPTER — simulated business system backed by local SQLite. "
    "Not a production integration."
)
