"""BlockID issuer service: the ONLY component that holds keys and sends transactions.

It acts exclusively on Postgres rows (studio.*) that an admin has already approved; the HTTP surface
(app.py, internal :8090) only tells it which row to process. See docs/IMPLEMENTATION.md.
"""
