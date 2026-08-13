"""
competitors/hardees/ui
---------------------------------------------------------------------
Streamlit rendering functions for the Hardee's live API preview page
(../dashboard/page.py). Each module here renders one section of the page
and calls into ../services/ for all business logic and ../api/client.py
(indirectly, through services) for all network calls - no module here
builds a request payload or interprets a raw API field itself, per the
task's "Do not place all API logic directly inside one Streamlit page"
instruction (this applies to every file here just as much as to page.py).

Caching convention used throughout: every function that calls the API is
wrapped in `@st.cache_data`, with the `HardeesApiClient` argument named
`_client` (Streamlit's documented convention for "do not hash this
argument, and do not use it to distinguish cache entries either") - the
cache key is always the plain, hashable identifiers (store id, service,
category id, product id, cluster id, ...) that actually determine the
response. This is what keeps a normal Streamlit rerun (e.g. typing in an
unrelated widget) from re-hitting the network - see ../README.md
"Streamlit live API preview" for the full behavior contract.
---------------------------------------------------------------------
"""
