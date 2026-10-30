# Fixtures

`geosearch_*.json` are real responses from the NYC Planning Labs GeoSearch API
(`https://geosearch.planninglabs.nyc/v2/search?text=<query>&size=10`), recorded
2026-10-30. All queries are public addresses or place names. Re-record by hand
if the service changes shape; the tests pin the behavior we rely on.
