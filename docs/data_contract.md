# Data contract assumptions

Schema version: `v1`.

## Observation semantics

- One row represents a price or availability change for one retailer offer at one location.
- Observations are events, not crawl snapshots.
- Silence can mean unchanged state or missing collection; it is not automatically an outage.
- API windows are half-open: `[observed_from, observed_to)`.
- `observation_id` is the deduplication key.
- Timestamps must be timezone-aware and are normalized to UTC by the client.
- `canonical_product_id` is nullable.
- Product mappings and product metadata are frozen at export time, not historically versioned.
- Unit prices derived from frozen pack metadata are not treated as point-in-time facts.

## Required observation fields

`observation_id`, `observed_at`, `retailer_id`, `store_id`, `city_id`,
`retailer_product_id`, `price`, `currency`, `is_available`, and `is_promotion`.

The remaining agreed API fields are retained when present and validated for type and
basic domain constraints.

## Publication boundary

Arzan.kz, retailer names, aggregate visualizations, and retailer-level findings may be
published. Raw observations and the product-link mapping are private. Public fixtures
must be synthetic unless separate written approval is received.

