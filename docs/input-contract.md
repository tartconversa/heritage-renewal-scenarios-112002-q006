# Input material

All records are synthetic and refer to no real household, project, or city. A file is a source extract, not a precomputed answer. Preserve source identifiers and revisions when interpreting it.

- `buildings.csv`: CSV; columns `building_id, block, protection_level, permitted_work, condition`. Dates use ISO 8601 where present; blank cells mean unknown or not supplied, not numeric zero.
- `proposals.csv`: CSV; columns `proposal_id, building_id, work, estimate_low, estimate_high, operator_id`. Dates use ISO 8601 where present; blank cells mean unknown or not supplied, not numeric zero.
- `access-links.csv`: CSV; columns `proposal_id, service_id, group_code, minutes_before, minutes_after`. Dates use ISO 8601 where present; blank cells mean unknown or not supplied, not numeric zero.
- `operations.csv`: CSV; columns `operator_id, service_id, capacity_per_day, confirmed_start`. Dates use ISO 8601 where present; blank cells mean unknown or not supplied, not numeric zero.
